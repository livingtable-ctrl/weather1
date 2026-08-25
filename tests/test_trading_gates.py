"""P0-2: LiveTradingGate must block live orders when graduation/safety gates fail."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

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

    def test_accuracy_override_lifts_the_live_gate_end_to_end(self, monkeypatch):
        """AUD-0023: override_accuracy_halt()'s own docstring claims it
        "ALSO lifts trading_gates.LiveTradingGate's accuracy check" -- every
        other test in this class mocks paper.is_accuracy_halted directly, so
        that specific integration point (a real ACCURACY_HALT_OVERRIDE_PATH
        file reaching this gate through the real is_accuracy_halted()) was
        never exercised end-to-end. paper._ACCURACY_HALT_OVERRIDE_PATH is
        isolated to tmp_path by conftest.py's autouse isolate_paper_data
        fixture, so calling the real override function here is safe.
        is_accuracy_halted itself is intentionally left unmocked; every
        other gate is mocked to pass so this test proves only the override's
        wiring, not the underlying win-rate/SPRT logic (already covered by
        TestAccuracyHaltOverride in test_risk_control.py)."""
        import paper

        gate = self._gate()
        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            # Sanity: without an override, the real (unmocked) is_accuracy_halted
            # halts on the rigged win rate above, so the gate blocks too.
            allowed, reason = gate.check()
            assert not allowed
            assert "Accuracy" in reason

            paper.override_accuracy_halt(reason="test", minutes=30)
            allowed, reason = gate.check()
        assert allowed
        assert reason == "ok"

    def test_expired_accuracy_override_does_not_lift_the_live_gate(self, monkeypatch):
        """Companion to the override test above: an EXPIRED override must
        NOT lift the live gate -- the time-boxing is the override's whole
        safety property (see override_accuracy_halt's docstring), and this
        end-to-end path is exactly as untested pre-fix as the active-override
        case."""
        import json
        import time

        import paper

        gate = self._gate()
        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        paper._ACCURACY_HALT_OVERRIDE_PATH.write_text(
            json.dumps(
                {
                    "expires_at": time.time() - 60,
                    "reason": "already expired",
                    "minutes": 1,
                }
            )
        )
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
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
        # is_daily_loss_halted(client) takes a client arg (main.py passes
        # client so the halt check includes unrealized MTM) -- a zero-arg
        # lambda here would TypeError and get silently swallowed by
        # _quick_paper_buy's own fail-open `except Exception: pass`, making
        # this mock fictional even though the test still passes today.
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
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
        # is_daily_loss_halted(client) takes a client arg (main.py passes
        # client so the halt check includes unrealized MTM) -- a zero-arg
        # lambda here would TypeError and get silently swallowed by
        # _quick_paper_buy's own fail-open `except Exception: pass`, making
        # this mock fictional even though the test still passes today.
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
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


class TestCmdOrderLiveRecording:
    """backlog.txt "MANUAL cmd_order LIVE ORDERS..." entry: a real live
    fill placed through cmd_order must be recorded via
    execution_log/LivePositionStore (live=True, closes_position_id set for
    a closing sell), never absorbed into paper.place_paper_order() -- the
    original bug let the automated protective-exit scanner "close" a real
    live position in the books, via close_paper_early(), without ever
    touching the real position on the exchange.

    All gate checks pass in every test here (this entry is specifically
    about what happens to a fill that already got past the gate) --
    TestLiveTradingGate above covers the gate itself.
    """

    @contextmanager
    def _passing_gate_patches(self):
        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            yield

    def _fake_analysis_triple(self):
        """Minimal market/enriched/analysis triple covering every field
        cmd_order's post-fill recording block reads -- used only by the
        tests that need the Brier-tracking branch to actually run (the
        positive-control paper test and the fully-analyzed live test);
        tests focused purely on live-position bookkeeping use
        get_market.return_value = None instead, since that block is
        independent of _is_live's own recording branch.

        Batch-60 item 2: the ticker/close_time/target_date are derived from
        TOMORROW rather than the old hardcoded 2026-04-17 literal. cmd_order's
        live BUY path now runs paper.validate_target_date_freshness() before
        placing, so a fixture frozen months in the past no longer represents
        an order that can reach the exchange at all -- and patching the
        staleness grace to swallow it would have masked exactly the guard
        these tests sit downstream of. All three fields move together so the
        triple stays internally consistent (a real KXHIGH-NYC-<date> market's
        target_date always matches its own ticker's embedded date); call
        sites read fake_market["ticker"] instead of a literal."""
        import paper

        _target = paper.utc_today() + timedelta(days=1)
        # Month abbreviation from a fixed table, not strftime("%b") --
        # opus-review-caught (F15): %b is locale-dependent, so on a
        # non-English runner the ticker's month segment would silently
        # change shape. Nothing asserts on it today, but Kalshi's own
        # tickers are always these three ASCII letters.
        _mon = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
        _ticker = (
            f"KXHIGH-NYC-{_target.year % 100:02d}"
            f"{_mon[_target.month - 1]}{_target.day:02d}-T70"
        )
        fake_market = {
            "ticker": _ticker,
            "close_time": f"{_target.isoformat()}T20:00:00Z",
        }
        fake_enriched = dict(fake_market, _city="NYC", _date=None)
        fake_analysis = {
            "forecast_prob": 0.65,
            "market_prob": 0.50,
            "net_edge": 0.10,
            "kelly": 0.05,
            "method": "ensemble",
            "days_out": 1,
            "target_date": _target.isoformat(),
            "condition": {"type": "high_temp", "threshold": 70},
            "model_forecast_means": {},
            "forecast_temp": 71.0,
        }
        return fake_market, fake_enriched, fake_analysis

    def test_live_buy_logs_live_true_not_a_paper_trade(self, monkeypatch):
        """The core fix: a real live BUY via cmd_order must be logged
        live=True in execution_log and must NOT create a paper_trades.json
        row -- before the fix, place_paper_order() unconditionally absorbed
        every cmd_order fill into the paper ledger regardless of action."""
        import execution_log
        import main
        import paper
        from kalshi_client import PROD_BASE

        fake_market, fake_enriched, fake_analysis = self._fake_analysis_triple()
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = fake_market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            # Kalshi's real status enum is resting/canceled/executed -- there
            # is no "filled" (order_executor._kalshi_status_to_internal's own
            # docstring). Mocking "filled" directly is exactly the gap that
            # let the pre-fix status-passthrough bug slip past this suite
            # undetected (opus review, 2026-08-17).
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
            self._passing_gate_patches(),
        ):
            main.cmd_order(
                mock_client, "buy", [fake_market["ticker"], "yes", "5", "0.40"]
            )

        mock_client.place_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live, fill_quantity, closes_position_id FROM orders "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 1
        assert row["fill_quantity"] == 5
        assert row["closes_position_id"] is None
        # The actual bug: this fill must not also land in the paper ledger,
        # where the automated protective-exit scanner could later mark it
        # "closed" in the books without ever touching the real position.
        assert paper.get_all_trades() == []

    def test_live_buy_bookkeeping_failure_does_not_report_order_as_failed(
        self, monkeypatch, capsys
    ):
        """Opus review follow-up (round 2): cmd_order's post-placement
        bookkeeping write (log_order_result recording the fill) used to
        share a try with the placement call itself -- a failure there (e.g.
        a locked DB) after a genuinely successful placement would have
        wrongly marked a REAL live order 'failed' (every dedup guard
        excludes 'failed', so the position could go untracked and be
        re-orderable) and, since cmd_order's except re-raises, surfaced as
        an uncaught exception to the operator despite the order having
        actually landed on the exchange. Must instead: not raise, not print
        'Order failed', and warn about the bookkeeping gap specifically."""
        import main
        from kalshi_client import PROD_BASE

        fake_market, fake_enriched, fake_analysis = self._fake_analysis_triple()
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = fake_market
        mock_client.place_order.return_value = {
            "order_id": "ord_bk_fail",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
            self._passing_gate_patches(),
            patch(
                "execution_log.log_order_result",
                side_effect=RuntimeError("db is locked"),
            ),
        ):
            # Must not raise -- the order genuinely landed on the exchange.
            main.cmd_order(
                mock_client, "buy", [fake_market["ticker"], "yes", "5", "0.40"]
            )

        mock_client.place_order.assert_called_once()
        out = capsys.readouterr().out.lower()
        assert "order failed" not in out
        assert "bookkeeping" in out

    def test_demo_buy_still_creates_paper_trade_positive_control(self, monkeypatch):
        """Positive control for the test above: a DEMO (non-live) buy, with
        the exact same analysis mocks, must still go through
        place_paper_order() and stay live=False in execution_log --
        proving the paper-recording branch is real, reachable code (not
        vacuously dead after the fix), so the live test's "no paper trade
        created" assertion is meaningful rather than trivially true."""
        import execution_log
        import main
        import paper
        from kalshi_client import DEMO_BASE

        fake_market, fake_enriched, fake_analysis = self._fake_analysis_triple()
        mock_client = MagicMock()
        mock_client.base_url = DEMO_BASE
        mock_client.get_market.return_value = fake_market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        # _fake_analysis_triple's target_date is a fixed placeholder,
        # unrelated to place_paper_order's target_date-freshness guard.
        monkeypatch.setattr(paper, "STALE_TARGET_DATE_GRACE_DAYS", 10_000)

        with (
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
        ):
            main.cmd_order(
                mock_client, "buy", [fake_market["ticker"], "yes", "5", "0.40"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 0
        trades = paper.get_all_trades()
        assert len(trades) == 1
        assert trades[0]["ticker"] == fake_market["ticker"]
        assert trades[0]["quantity"] == 5

    def test_live_buy_partial_fill_records_correct_fill_quantity(self, monkeypatch):
        """Adjacency fix caught during the same investigation: cmd_order
        previously never passed fill_quantity to log_order_result at all,
        so _get_live_open_positions()'s `fill_quantity or quantity`
        fallback would have tracked a partially-filled live BUY at its full
        REQUESTED size (5) instead of what actually filled (3)."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE
        from order_executor import _get_live_open_positions

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None  # skip analysis branch
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            # Live orders are IOC as of this fix: Kalshi has no distinct
            # "partially filled" status -- an IOC order that matches some
            # contracts and cancels the remainder reports "canceled" with a
            # nonzero fill count (order_executor._kalshi_status_to_internal's
            # own F9 docstring), which _kalshi_status_to_internal promotes to
            # "filled" internally. Only 3 of the 5 requested contracts
            # matched before the rest was canceled.
            "status": "canceled",
            "fill_count_fp": "3.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT fill_quantity FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["fill_quantity"] == 3
        open_positions = _get_live_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0]["quantity"] == 3

    def test_live_sell_closes_matching_tracked_position(self, monkeypatch):
        """A live SELL that matches an existing tracked open live position
        (the common real sequence: opened automatically by
        `watch --auto --live`, closed manually via cmd_order) must close
        THAT position via closes_position_id + record_live_exit_fill, not
        open a brand-new phantom paper position at the sell's price."""
        import execution_log
        import main
        import paper
        from kalshi_client import PROD_BASE

        position_id = execution_log.log_order(
            ticker="KXHIGH-NYC-26APR17-T70",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(position_id, status="filled", fill_quantity=10)

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "status": "executed",
            "fill_count_fp": "10.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        with execution_log._conn() as con:
            position_row = con.execute(
                "SELECT settled_at, pnl FROM orders WHERE id = ?", (position_id,)
            ).fetchone()
            exit_row = con.execute(
                "SELECT live, closes_position_id FROM orders WHERE id != ? "
                "ORDER BY id DESC LIMIT 1",
                (position_id,),
            ).fetchone()
        assert position_row["settled_at"] is not None
        # Batch-22 items 3+6: gross_pnl = 10 * (0.60 - 0.40) = 2.00; real
        # curved fee (utils.kalshi_taker_fee): ceil(0.07*10*0.60*0.40*100)/100
        # = 0.17. pnl = 2.00 - 0.17 = 1.83.
        assert position_row["pnl"] == pytest.approx(1.83)
        assert exit_row["live"] == 1
        assert exit_row["closes_position_id"] == position_id
        # Must not also open a phantom NEW paper position at the sell price
        # -- the exact bug class this fix resolves.
        assert paper.get_all_trades() == []

    def _two_tracked_live_positions(self, ticker, older_qty, newer_qty):
        """Two filled-unsettled live positions on the same ticker+side,
        oldest first (placed_at ascending, matching
        get_filled_unsettled_live_orders()'s own ORDER BY). Entry prices are
        deliberately DIFFERENT (0.40 / 0.45) so a cascade that credited the
        wrong position's entry price would produce visibly wrong P&L rather
        than silently matching."""
        import execution_log

        older_id = execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=older_qty,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            older_id, status="filled", fill_quantity=older_qty
        )
        newer_id = execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=newer_qty,
            price=0.45,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            newer_id, status="filled", fill_quantity=newer_qty
        )
        assert older_id != newer_id
        return older_id, newer_id

    def _sell_client(self, fill_count):
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "status": "executed",
            "fill_count_fp": f"{fill_count}.00",
        }
        return mock_client

    def _sell_patches(self, monkeypatch):
        import main

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    def test_live_sell_smaller_than_oldest_position_leaves_newer_untouched(
        self, monkeypatch, capsys
    ):
        """AUD-0055: more than one tracked open live position can legally
        share a ticker+side. When the fill fits entirely inside the OLDEST
        one, the cascade added in batch-60 must still behave exactly as
        before -- close that position, leave the newer one open and
        unmodified -- and still warn the operator that this order's
        closes_position_id names only the first of the matches."""
        import execution_log
        import main
        import paper
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 10, 5
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        captured = capsys.readouterr()
        # (a) the operator warning prints, naming the linked position.
        assert "oldest-first" in captured.out
        assert f"#{older_id}" in captured.out

        with execution_log._conn() as con:
            older_row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (older_id,)
            ).fetchone()
            newer_row = con.execute(
                "SELECT settled_at, closes_position_id FROM orders WHERE id = ?",
                (newer_id,),
            ).fetchone()
            exit_row = con.execute(
                "SELECT closes_position_id FROM orders WHERE id NOT IN (?, ?) "
                "ORDER BY id DESC LIMIT 1",
                (older_id, newer_id),
            ).fetchone()
        # (b) exactly the oldest is closed.
        assert older_row["settled_at"] is not None
        assert exit_row["closes_position_id"] == older_id
        # (c) the newer position remains open and untouched.
        assert newer_row["settled_at"] is None
        assert newer_row["closes_position_id"] is None
        # Positive control: the newer position must still be a real,
        # queryable open position afterward -- not just "not closed" by
        # accident of a field this test forgot to check.
        remaining = _get_live_open_positions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == newer_id
        assert paper.get_all_trades() == []

    def test_live_sell_spanning_two_positions_settles_both(self, monkeypatch):
        """Batch-60 item 4, the bug this replaces oldest-only with: a sell
        whose fill SPANS more than one tracked position. Before the FIFO
        cascade, the whole count went to the oldest match alone and
        record_live_exit_fill clamped it to that position's own quantity --
        so selling 10 against positions of 4 and 6 fully closed the 4 and
        left the 6 marked open in execution_log with no contracts behind it
        on the exchange, overstating open exposure and inviting the
        protective-exit scanner to try selling them again.

        Both positions must now settle, each against its OWN entry price
        (0.40 and 0.45 -- deliberately different, so crediting the wrong one
        would show up as wrong P&L rather than a coincidental match)."""
        import execution_log
        import main
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 6
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        with execution_log._conn() as con:
            older_row = con.execute(
                "SELECT settled_at, pnl FROM orders WHERE id = ?", (older_id,)
            ).fetchone()
            newer_row = con.execute(
                "SELECT settled_at, pnl FROM orders WHERE id = ?", (newer_id,)
            ).fetchone()
        # Hand-computed (utils.kalshi_taker_fee = ceil(0.07*C*P*(1-P)*100)/100
        # at the 0.60 exit price):
        #   older: gross 4*(0.60-0.40)=0.80, fee ceil(6.72)/100=0.07 -> 0.73
        #   newer: gross 6*(0.60-0.45)=0.90, fee ceil(10.08)/100=0.11 -> 0.79
        assert older_row["settled_at"] is not None
        assert older_row["pnl"] == pytest.approx(0.73)
        assert newer_row["settled_at"] is not None
        assert newer_row["pnl"] == pytest.approx(0.79)
        # Nothing is left claiming to hold contracts that no longer exist.
        assert _get_live_open_positions() == []

    def test_live_sell_spanning_positions_partially_reduces_the_last_one(
        self, monkeypatch
    ):
        """Batch-60 item 4, the mixed case: the fill closes the oldest match
        outright and lands PARTWAY into the next one. The second position
        must stay open at its reduced size (not be closed, and not be left
        at its original size), and that partial leg's P&L must land on the
        SELL order's own row -- AUD-0028's rule, which the cascade has to
        preserve for the one position it partially reduces."""
        import execution_log
        import main
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 6
        )
        mock_client = self._sell_client(7)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "7", "0.60"]
            )

        with execution_log._conn() as con:
            older_row = con.execute(
                "SELECT settled_at, pnl FROM orders WHERE id = ?", (older_id,)
            ).fetchone()
            newer_row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (newer_id,)
            ).fetchone()
            exit_row = con.execute(
                "SELECT id, settled_at, pnl, closes_position_id, fill_quantity "
                "FROM orders WHERE id NOT IN (?, ?) ORDER BY id DESC LIMIT 1",
                (older_id, newer_id),
            ).fetchone()
        # older: 4 of 4 -> full close, pnl 0.73 (same math as the test above).
        assert older_row["settled_at"] is not None
        assert older_row["pnl"] == pytest.approx(0.73)
        # newer: 3 of 6 -> stays open, reduced to 3.
        assert newer_row["settled_at"] is None
        remaining = _get_live_open_positions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == newer_id
        assert remaining[0]["quantity"] == 3
        # The partial leg's P&L lands on the sell order's own row:
        #   gross 3*(0.60-0.45)=0.45, fee ceil(0.07*3*0.24*100)/100=0.06 -> 0.39
        assert exit_row["settled_at"] is not None
        assert exit_row["pnl"] == pytest.approx(0.39)
        # ...and that row must be attributed to the position the leg was
        # actually taken from -- the NEWER one -- not to the oldest match
        # closes_position_id was pre-set to before placement. An earlier
        # version of this test asserted `== older_id`, pinning the bug:
        # export_live_tax_csv self-joins on closes_position_id for the entry
        # price, so it reported this 0.39 (earned against a 0.45 entry)
        # against the older position's 0.40, and counted the whole 7-contract
        # fill as this leg's quantity. See test_tax_export_after_a_spanning_
        # cascade_reports_each_leg_once for the export-level assertion.
        assert exit_row["closes_position_id"] == newer_id
        assert exit_row["fill_quantity"] == 3

    def test_tax_export_after_a_spanning_cascade_reports_each_leg_once(
        self, monkeypatch, tmp_path
    ):
        """Opus review, F2 -- the defect the cascade introduced, measured at
        the artifact that matters. Positions of 4 @0.40 and 20 @0.45, sell 10:
        the export must show 4 contracts at a 0.40 basis and 6 at a 0.45
        basis, totalling exactly the 10 that were sold. Before the
        attribution fix it showed 4 @0.40 and 10 @0.40 -- 14 contracts
        disposed for a 10-contract sale, the second leg against the wrong
        position's cost basis."""
        import csv

        import execution_log
        import main

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 20
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )
        assert newer_id  # the partially-reduced leg is the one under test

        _csv = tmp_path / "tax.csv"
        assert execution_log.export_live_tax_csv(str(_csv)) == 2
        with open(_csv, newline="") as _fh:
            rows = list(csv.DictReader(_fh))

        assert sum(int(r["quantity"]) for r in rows) == 10
        by_qty = {int(r["quantity"]): r for r in rows}
        assert set(by_qty) == {4, 6}
        assert float(by_qty[4]["entry_price"]) == pytest.approx(0.40)
        assert float(by_qty[6]["entry_price"]) == pytest.approx(0.45)
        # Positive control: the two legs really are distinct dispositions
        # with their own P&L, not one row double-counted.
        #   4 @0.40 -> 4*(0.60-0.40) - 0.07 = 0.73
        #   6 @0.45 -> 6*(0.60-0.45) - 0.11 = 0.79
        assert float(by_qty[4]["pnl"]) == pytest.approx(0.73)
        assert float(by_qty[6]["pnl"]) == pytest.approx(0.79)

    def test_a_position_settled_mid_flight_is_skipped_not_fatal(
        self, monkeypatch, capsys
    ):
        """Opus review, F11. _live_open_matches is snapshotted before
        client.place_order, so cron or `watch --auto --live` can settle the
        oldest match in that window. record_live_exit_fill signals exactly
        that with RuntimeError -- meaning those contracts were never ours to
        attribute, so the fill belongs to the NEXT match undiminished.
        Treating it like an unknown failure aborted the whole cascade and
        left 100% of a real sale unattributed, reintroducing the very
        phantom-open-position state item 4 exists to prevent."""
        import execution_log
        import main
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 20
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        _real_fill = execution_log.record_live_exit_fill
        _calls = []

        def _race_the_oldest(position, fill_count, exit_price, reason=None):
            _calls.append((position["id"], fill_count))
            if position["id"] == older_id:
                # Genuinely settle the row before raising, so the post-state
                # matches a REAL concurrent close rather than only simulating
                # the exception. Without this the older position stays open
                # and the assertions below would be measuring a half-applied
                # scenario that cannot occur in production.
                execution_log.record_live_early_exit(
                    older_id, 0.58, "raced_by_cron", 0.65
                )
                raise RuntimeError(
                    "position was already settled by a concurrent writer"
                )
            return _real_fill(position, fill_count, exit_price, reason)

        with (
            self._passing_gate_patches(),
            patch("execution_log.record_live_exit_fill", _race_the_oldest),
        ):
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        out = capsys.readouterr().out
        # The whole fill moves to the surviving match, undiminished -- 10,
        # not 10 minus the raced position's 4.
        assert _calls == [(older_id, 4), (newer_id, 10)]
        assert "not attributed" not in out
        remaining = _get_live_open_positions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == newer_id
        assert remaining[0]["quantity"] == 10  # 20 - 10
        # Positive control that the surviving leg genuinely settled rather
        # than the cascade silently doing nothing: its P&L is on the books.
        #   10 @0.45 -> 10*(0.60-0.45) - 0.17 = 1.33
        with execution_log._conn() as con:
            exit_row = con.execute(
                "SELECT pnl, closes_position_id FROM orders "
                "WHERE id NOT IN (?, ?) ORDER BY id DESC LIMIT 1",
                (older_id, newer_id),
            ).fetchone()
        assert exit_row["pnl"] == pytest.approx(1.33)
        assert exit_row["closes_position_id"] == newer_id

    def test_live_sell_exceeding_all_tracked_positions_warns(self, monkeypatch, capsys):
        """Batch-60 item 4: a sell larger than everything this bot tracks
        for the ticker+side. Every match settles, and the leftover is
        reported rather than silently absorbed -- the old oldest-only code
        clamped to one position's quantity and said nothing at all, so an
        operator had no signal that most of the sale was unaccounted for."""
        import execution_log
        import main
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 6
        )
        mock_client = self._sell_client(12)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "12", "0.60"]
            )

        out = capsys.readouterr().out
        assert "2 of 12 sold contracts exceeded" in out
        # Positive control: the warning is about a genuine leftover, not a
        # cascade that failed to run -- both tracked positions did settle.
        with execution_log._conn() as con:
            settled = con.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE id IN (?, ?) "
                "AND settled_at IS NOT NULL",
                (older_id, newer_id),
            ).fetchone()
        assert settled["n"] == 2
        assert _get_live_open_positions() == []

    def test_live_sell_cascade_stops_and_warns_when_a_settle_fails(
        self, monkeypatch, capsys
    ):
        """Batch-60 item 4: if settling one match raises (e.g.
        record_live_exit_fill's concurrent-writer RuntimeError), the cascade
        must STOP rather than re-attribute that position's contracts to the
        next match -- silently settling someone else's row with them would
        corrupt attribution worse than leaving the remainder for manual
        reconciliation. The operator must be told how much is unattributed."""
        import execution_log
        import main
        from order_executor import _get_live_open_positions

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 6
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        _real_fill = execution_log.record_live_exit_fill
        _calls = []

        def _fail_on_second(position, fill_count, exit_price, reason=None):
            _calls.append(position["id"])
            if len(_calls) > 1:
                # Deliberately NOT a RuntimeError: that type means one
                # specific, benign thing (a concurrent writer got there
                # first) and is handled by skipping to the next match --
                # see test_a_position_settled_mid_flight_is_skipped_not_fatal.
                # This is the unknown-cause path, where stopping is correct.
                raise sqlite3.OperationalError("database is locked")
            return _real_fill(position, fill_count, exit_price, reason)

        with (
            self._passing_gate_patches(),
            patch("execution_log.record_live_exit_fill", _fail_on_second),
        ):
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        out = capsys.readouterr().out
        assert "6 of 10 sold contracts are not attributed" in out
        # Positive control for the "stopped early" claim: the cascade really
        # did reach the second match (so the stop is the raise, not a loop
        # that never iterated), and the FIRST match still settled normally.
        assert _calls == [older_id, newer_id]
        with execution_log._conn() as con:
            older_row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (older_id,)
            ).fetchone()
        assert older_row["settled_at"] is not None
        remaining = _get_live_open_positions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == newer_id
        assert remaining[0]["quantity"] == 6

    def test_a_position_merely_reduced_mid_flight_keeps_its_own_share(
        self, monkeypatch, capsys
    ):
        """Opus round-2 review, MEDIUM-1 -- a bug the F11 fix introduced.
        record_live_exit_fill does NOT raise RuntimeError for one cause: its
        partial branch also fires when record_live_partial_exit finds
        COALESCE(fill_quantity, quantity) < filled_count, i.e. the position
        is STILL OPEN with real contracts, just smaller than our snapshot.
        F11's blanket `continue` then shifted that position's entire share
        onto the next match at the WRONG cost basis -- worse than the abort
        it replaced, which at least left the discrepancy visible.

        Here cron reduces the oldest (20 @0.40) to 2 mid-flight while the
        operator sells 10. Correct FIFO attribution is 2 @0.40 + 8 @0.45,
        not 10 @0.45."""
        import execution_log
        import main

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 20, 10
        )
        mock_client = self._sell_client(10)
        self._sell_patches(monkeypatch)

        _real_fill = execution_log.record_live_exit_fill
        _reduced = []

        def _reduce_the_oldest(position, fill_count, exit_price, reason=None):
            if position["id"] == older_id and not _reduced:
                # Genuinely shrink the row (settled_at stays NULL), exactly
                # as a concurrent protective exit would, then raise the way
                # record_live_partial_exit's guard makes the real function
                # raise for this case.
                _reduced.append(True)
                execution_log.record_live_partial_exit(older_id, 18)
                raise RuntimeError(
                    f"position {older_id} was settled or reduced below "
                    f"{fill_count} by a concurrent writer -- not applying "
                    "this partial exit"
                )
            return _real_fill(position, fill_count, exit_price, reason)

        with (
            self._passing_gate_patches(),
            patch("execution_log.record_live_exit_fill", _reduce_the_oldest),
        ):
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        with execution_log._conn() as con:
            older_row = con.execute(
                "SELECT settled_at, pnl FROM orders WHERE id = ?", (older_id,)
            ).fetchone()
            exit_row = con.execute(
                "SELECT pnl, closes_position_id FROM orders "
                "WHERE id NOT IN (?, ?) ORDER BY id DESC LIMIT 1",
                (older_id, newer_id),
            ).fetchone()
        from order_executor import _get_live_open_positions

        # The retry took the oldest's real remaining 2 at ITS OWN 0.40 basis:
        #   2*(0.60-0.40) - ceil(0.07*2*0.24*100)/100 = 0.40 - 0.04 = 0.36
        assert older_row["settled_at"] is not None
        assert older_row["pnl"] == pytest.approx(0.36)
        # ...leaving 8 for the newer at 0.45. That leg is a PARTIAL (8 of
        # 10), so per AUD-0028 its P&L lands on the sell order's own row,
        # attributed to the newer position:
        #   8*(0.60-0.45) - ceil(0.07*8*0.24*100)/100 = 1.20 - 0.14 = 1.06
        # Positive control against the bug this test exists for: crediting
        # all 10 to the newer would give 10*(0.60-0.45) - 0.17 = 1.33, and
        # would have FULLY closed it instead of leaving 2 open.
        assert exit_row["pnl"] == pytest.approx(1.06)
        assert exit_row["pnl"] != pytest.approx(1.33)
        assert exit_row["closes_position_id"] == newer_id
        remaining = _get_live_open_positions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == newer_id
        assert remaining[0]["quantity"] == 2

    def test_oversell_leftover_is_actually_recorded_on_the_sell_row(
        self, monkeypatch, capsys
    ):
        """Opus round-2 review, MEDIUM-2 -- also introduced by this batch.
        The over-sell warning said the leftover was "recorded on this
        order's row only", which was categorically false: reaching that
        branch requires no leg to have been partial, and the sell row is
        settled ONLY inside the partial branch. So row_id sat at
        settled_at=NULL/pnl=NULL, excluded from export_live_tax_csv,
        get_live_pnl_summary, get_live_settlement_streak and (via its
        non-NULL closes_position_id) get_filled_unsettled_live_orders -- the
        contracts were recorded precisely nowhere, on the one screen an
        operator uses to reconcile a real sale."""
        import execution_log
        import main

        older_id, newer_id = self._two_tracked_live_positions(
            "KXHIGH-NYC-26APR17-T70", 4, 6
        )
        mock_client = self._sell_client(12)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "12", "0.60"]
            )

        out = capsys.readouterr().out
        assert "2 of 12 sold contracts exceeded" in out
        assert "recorded nowhere" not in out

        with execution_log._conn() as con:
            exit_row = con.execute(
                "SELECT settled_at, pnl, exit_reason, closes_position_id, "
                "fill_quantity FROM orders WHERE id NOT IN (?, ?) "
                "ORDER BY id DESC LIMIT 1",
                (older_id, newer_id),
            ).fetchone()
        # Settled with the same unmatched-sell placeholder shape the
        # no-match-at-all branch already uses, so export_live_tax_csv labels
        # it "unmatched_sell_unknown_pnl" with an empty pnl cell rather than
        # dropping it or asserting a fabricated $0.00 profit.
        assert exit_row["settled_at"] is not None
        assert exit_row["exit_reason"] == "unmatched_sell"
        # ...and byte-identical in SHAPE to that branch, which is what the
        # export actually reads (opus round-3 review). An earlier version of
        # this test stopped at the two assertions above while
        # closes_position_id still named the oldest match and fill_quantity
        # was the WHOLE fill -- so the export reported the 2-contract
        # remainder as 12 contracts against that position's cost basis.
        assert exit_row["closes_position_id"] is None
        assert exit_row["fill_quantity"] == 2
        # Positive control: the two real legs still settled normally, so
        # this is measuring the leftover and not a cascade that failed.
        with execution_log._conn() as con:
            settled = con.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE id IN (?, ?) "
                "AND settled_at IS NOT NULL",
                (older_id, newer_id),
            ).fetchone()
        assert settled["n"] == 2

    def test_tax_export_after_an_oversell_counts_the_remainder_once(
        self, monkeypatch, tmp_path
    ):
        """Opus round-3 review: the round-2 leftover fix measured where it
        actually matters. Positions 4 @0.40 and 6 @0.45, sell 12 -> the
        export must total exactly the 12 contracts sold: 4 + 6 real legs
        plus a 2-contract unmatched remainder carrying NO cost basis.
        Before this it totalled 22, with the 0.40 basis reported twice."""
        import csv

        import execution_log
        import main

        self._two_tracked_live_positions("KXHIGH-NYC-26APR17-T70", 4, 6)
        mock_client = self._sell_client(12)
        self._sell_patches(monkeypatch)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "12", "0.60"]
            )

        _csv = tmp_path / "tax.csv"
        assert execution_log.export_live_tax_csv(str(_csv)) == 3
        with open(_csv, newline="") as _fh:
            rows = list(csv.DictReader(_fh))

        assert sum(int(r["quantity"]) for r in rows) == 12
        _unmatched = [r for r in rows if r["outcome"] == "unmatched_sell_unknown_pnl"]
        assert len(_unmatched) == 1
        assert int(_unmatched[0]["quantity"]) == 2
        # Empty pnl cell, not a fabricated 0.00 -- "needs manual entry".
        assert _unmatched[0]["pnl"] == ""
        # Positive control: the two real legs are still each reported once,
        # against their OWN distinct bases, so the total isn't right by way
        # of two errors cancelling.
        _real = sorted(
            (int(r["quantity"]), float(r["entry_price"]))
            for r in rows
            if r["outcome"] != "unmatched_sell_unknown_pnl"
        )
        assert _real == [(4, 0.40), (6, 0.45)]

    def test_live_sell_partial_fill_settles_own_exit_row_pnl(self, monkeypatch):
        """AUD-0028: a PARTIAL matched-sell fill must settle the sell
        order's OWN row (not just the position row), mirroring
        order_executor._exit_live_position's identical partial-fill branch
        -- otherwise this sold lot's P&L never gets its own tax-CSV row and
        never counts toward get_live_pnl_summary, reproducing the
        'aggregate-only P&L' bug an earlier same-day commit fixed for the
        automated exit path."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        position_id = execution_log.log_order(
            ticker="KXHIGH-NYC-26APR17-T70",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(position_id, status="filled", fill_quantity=10)

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_exit_partial",
            # IOC order that only matched 6 of the 10 requested before the
            # remainder was auto-canceled -- Kalshi reports this as
            # "canceled" with a nonzero fill count.
            "status": "canceled",
            "fill_count_fp": "6.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "10", "0.60"]
            )

        with execution_log._conn() as con:
            position_row = con.execute(
                "SELECT settled_at, fill_quantity FROM orders WHERE id = ?",
                (position_id,),
            ).fetchone()
            exit_row = con.execute(
                "SELECT settled_at, exit_reason, pnl, closes_position_id "
                "FROM orders WHERE id != ? ORDER BY id DESC LIMIT 1",
                (position_id,),
            ).fetchone()
        # The POSITION stays open at its reduced size -- unchanged behavior.
        assert position_row["settled_at"] is None
        assert position_row["fill_quantity"] == 4
        # The exit order's OWN row must now be settled with its own P&L --
        # this is the actual fix; before it, exit_row["settled_at"] stayed
        # NULL forever (harmless for open-position detection, since
        # closes_position_id is set, but the P&L silently never surfaced
        # anywhere queryable).
        assert exit_row["settled_at"] is not None
        assert exit_row["exit_reason"] == "manual_close"
        assert exit_row["closes_position_id"] == position_id
        # gross_pnl = 6 * (0.60 - 0.40) = 1.20; fee = ceil(0.07*6*0.60*
        # 0.40*100)/100 = 0.11. pnl = 1.20 - 0.11 = 1.09.
        assert exit_row["pnl"] == pytest.approx(1.09)
        # Positive control: this settled row must be real enough to actually
        # surface in the aggregate P&L summary, not just present in the DB.
        summary = execution_log.get_live_pnl_summary()
        assert summary["total_pnl"] == pytest.approx(1.09)

    def test_live_sell_with_no_matching_position_logs_live_no_paper_mirror(
        self, monkeypatch
    ):
        """Per the explicit design decision: a live SELL with no matching
        tracked live position (e.g. reducing a position this bot has no
        live row for) still reaches the real exchange either way -- record
        it correctly as live=True/closes_position_id=None instead of
        silently mislabeling it live=False or routing it into
        paper.place_paper_order() (which would open a brand-new phantom
        entry at the sell's price, the exact bug this fix resolves).

        Opus review (2026-08-17), NEW-H1: live=True/status='filled'/
        settled_at=NULL/closes_position_id=NULL is EXACTLY the shape
        get_filled_unsettled_live_orders() treats as an open LONG position
        -- left alone, this reduce-only sell would be misread as a
        brand-new entry the bot just bought, and the protective-exit
        scanner would later place a REAL exit sell against it. The row
        must be immediately self-settled so it can never be mistaken for
        one -- this is the actual regression proof, not just the live/
        closes_position_id field checks above."""
        import execution_log
        import main
        import paper
        from kalshi_client import PROD_BASE
        from order_executor import _get_live_open_positions

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.60"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live, closes_position_id, settled_at FROM orders "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 1
        assert row["closes_position_id"] is None
        # The actual regression proof: this row must never be readable as
        # an open position, regardless of how it got there.
        assert row["settled_at"] is not None
        assert _get_live_open_positions() == []
        assert paper.get_all_trades() == []

    def test_unmatched_sell_settle_failure_warns_operator_not_reassures(
        self, monkeypatch, capsys
    ):
        """Opus review follow-up (AUD-0026): when record_live_early_exit_with_retry
        exhausts every retry, the row genuinely stays live=1/status='filled'/
        settled_at=NULL -- an OPEN-position-shaped phantom, exactly what this
        whole branch exists to prevent. A prior version of this fix printed
        the reassuring 'recorded, not left open as a phantom position'
        message UNCONDITIONALLY, ignoring the wrapper's return value --
        proving the console must instead surface a clear warning naming the
        still-unsettled row."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        monkeypatch.setattr(
            "execution_log.record_live_early_exit_with_retry",
            lambda *args, **kwargs: False,
        )

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.60"]
            )

        out = capsys.readouterr().out
        assert "not left open as a phantom position" not in out
        assert "could not" in out.lower()
        # Positive control: the row genuinely IS still unsettled (the mock
        # never touched the real DB write) -- proves the warning reflects
        # real state, not just a hardcoded string.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["settled_at"] is None

    def test_live_order_placed_immediate_or_cancel(self, monkeypatch):
        """Opus review (2026-08-17): live orders must be placed IOC, not the
        GTC default -- a resting order has no path back to being recognized
        as a manageable position (no code teaches the general poller about
        closes_position_id), which would silently orphan the fix. Confirmed
        via AskUserQuestion as the deliberate trading-behavior tradeoff."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
            )

        mock_client.place_order.assert_called_once()
        _args, _kwargs = mock_client.place_order.call_args
        assert _args == ("KXHIGH-NYC-26APR17-T70", "yes", "buy", 5, 0.40)
        assert _kwargs["time_in_force"] == "immediate_or_cancel"
        # cycle= is time-derived (order_executor._current_forecast_cycle()),
        # not asserted to an exact value -- just that it's threaded through
        # for idempotency, not silently omitted.
        assert _kwargs.get("cycle")
        # AUD-0003: order_type must mirror this IOC placement ("market", not
        # "buy") -- order_executor._poll_pending_orders' settlement-fee
        # selection reads this column to tell a taker entry from a maker one.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT order_type FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["order_type"] == "market"

    def test_demo_order_stays_good_till_canceled(self, monkeypatch):
        """Positive control for the test above: demo/paper mode keeps the
        prior GTC default -- only the live path's order semantics change."""
        import execution_log
        import main
        from kalshi_client import DEMO_BASE

        mock_client = MagicMock()
        mock_client.base_url = DEMO_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        main.cmd_order(
            mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
        )

        mock_client.place_order.assert_called_once()
        _args, _kwargs = mock_client.place_order.call_args
        assert _args == ("KXHIGH-NYC-26APR17-T70", "yes", "buy", 5, 0.40)
        assert "time_in_force" not in _kwargs
        assert _kwargs.get("cycle")
        # AUD-0003 positive control: demo/paper keeps the GTC default, so
        # order_type must stay "limit" (maker) -- proves the "market" value
        # asserted in the live test above is genuinely IOC-driven, not a
        # hardcoded constant.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT order_type FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["order_type"] == "limit"

    def test_live_buy_zero_fill_canceled_records_nothing(self, monkeypatch):
        """A genuinely dead IOC order (no match at all -- Kalshi status
        "canceled" with a ZERO fill count) must record no live position and
        print a clear nothing-filled message, distinct from H2's
        canceled-with-partial-fill case."""
        import main
        import paper
        from kalshi_client import PROD_BASE
        from order_executor import _get_live_open_positions

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
            )

        assert _get_live_open_positions() == []
        assert paper.get_all_trades() == []

    def test_live_buy_records_close_time_entry_prob_forecast_cycle(self, monkeypatch):
        """Opus review (2026-08-17), H3: without close_time, a position fails
        positions._passes_exit_gates CLOSED (never exits via stop-loss/
        breakeven); without entry_prob, order_executor._check_live_model_exits
        skips it entirely. Both were previously never passed, silently
        leaving a cmd_order-opened live position structurally unmanageable
        even after the rest of this fix routes it into execution_log."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        fake_market, fake_enriched, fake_analysis = self._fake_analysis_triple()
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = fake_market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
            self._passing_gate_patches(),
        ):
            main.cmd_order(
                mock_client, "buy", [fake_market["ticker"], "yes", "5", "0.40"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT close_time, entry_prob, forecast_cycle FROM orders "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["close_time"] == fake_market["close_time"]
        assert row["entry_prob"] == pytest.approx(fake_analysis["forecast_prob"])
        assert row["forecast_cycle"] is not None

    def test_live_buy_prelogged_client_order_id_matches_what_place_order_posts(
        self, monkeypatch
    ):
        """Opus review follow-up (batch-22 item 2, F7): the pre-logged
        client_order_id is only useful for crash-recovery if it's actually
        the SAME id Kalshi received -- a call-site arg drift (e.g. count vs
        int(count), or a re-derived cycle) would silently defeat the whole
        fix while every other test here (which only checks the id is SOME
        valid hash) still passes. Spies on log_order's own response= kwarg
        at pre-log time (before log_order_result's later write overwrites
        the row), and independently re-derives the expected id from the
        args place_order() itself actually received, rather than trusting
        main.py's own internal computation for either side of the
        comparison."""
        import main
        from kalshi_client import PROD_BASE, compute_client_order_id

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None
        mock_client.place_order.return_value = {
            "order_id": "ord_cid_check",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        import execution_log as _el_module

        real_log_order = _el_module.log_order
        prelog_calls = []

        def _spy_log_order(*args, **kwargs):
            prelog_calls.append(kwargs)
            return real_log_order(*args, **kwargs)

        with (
            # cmd_order does `from execution_log import log_order, ...`
            # LOCALLY at call time -- patching execution_log's own module
            # attribute (not a nonexistent main.log_order) is what that
            # fresh import actually binds to.
            patch.object(_el_module, "log_order", side_effect=_spy_log_order),
            self._passing_gate_patches(),
        ):
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.40"]
            )

        mock_client.place_order.assert_called_once()
        _args, _kwargs = mock_client.place_order.call_args
        posted_cycle = _kwargs["cycle"]
        posted_tif = _kwargs["time_in_force"]
        expected_cid = compute_client_order_id(
            "KXTEST-25JUN01-T70", "yes", "buy", 5, 0.40, posted_tif, posted_cycle
        )

        assert len(prelog_calls) == 1
        assert prelog_calls[0]["response"]["client_order_id"] == expected_cid


class TestQuickPaperBuyMakerRecording:
    """AUD-0010: _quick_paper_buy()'s maker-order branch places a REAL live
    order via client.place_maker_order() but previously called zero
    execution_log persistence -- the exact same 'phantom unmanaged live
    position' failure mode TestCmdOrderLiveRecording above covers for
    cmd_order, just never fixed for this call site.

    Uses a PROD_BASE client + full gate-passing patches (not DEMO_BASE) for
    every "this is a real live order" test below -- opus review caught that
    the fix's own first draft hardcoded live=True regardless of the
    client's actual base_url, and these tests originally used DEMO_BASE
    (chosen only to skip the gate cheaply) while still asserting live==1,
    silently locking in that bug. TestLiveTradingGate above already covers
    the gate itself; _passing_gate_patches here exists purely so these
    tests can reach the bookkeeping logic with a client the code correctly
    recognizes as live."""

    @contextmanager
    def _passing_gate_patches(self):
        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            yield

    def _standard_inputs(self):
        return iter(
            [
                "KXTEST-25JUN01-T70",  # ticker
                "yes",  # side
                "2",  # order type: limit maker
                "0.45",  # limit price
                "5",  # qty
                "",  # thesis
            ]
        )

    def test_maker_order_success_logs_pending_row(self, monkeypatch):
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.return_value = {
            "order_id": "ord_maker_1",
            "status": "resting",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live, status, quantity, price FROM orders "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 1
        # Kalshi's real status enum is resting/canceled/executed -- a
        # resting maker order translates to None via
        # _kalshi_status_to_internal, defaulting to "pending" (the
        # established convention _place_live_order/cmd_order both use).
        assert row["status"] == "pending"
        assert row["quantity"] == 5
        assert row["price"] == pytest.approx(0.45)

    def test_maker_prelogged_client_order_id_matches_what_place_maker_order_posts(
        self, monkeypatch
    ):
        """Opus review follow-up (batch-22 item 2, F7): mirrors
        TestCmdOrderLiveRecording's matching test for this second manual
        live-order path."""
        import main
        from kalshi_client import PROD_BASE, compute_client_order_id

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.return_value = {
            "order_id": "ord_maker_cid_check",
            "status": "resting",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        import execution_log as _el_module

        real_log_order = _el_module.log_order
        prelog_calls = []

        def _spy_log_order(*args, **kwargs):
            prelog_calls.append(kwargs)
            return real_log_order(*args, **kwargs)

        with (
            patch.object(_el_module, "log_order", side_effect=_spy_log_order),
            self._passing_gate_patches(),
        ):
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_called_once()
        _args, _kwargs = mock_client.place_maker_order.call_args
        posted_cycle = _kwargs["cycle"]
        # place_maker_order always uses good_till_canceled internally (not a
        # kwarg of place_maker_order itself, unlike place_order above).
        expected_cid = compute_client_order_id(
            "KXTEST-25JUN01-T70",
            "yes",
            "buy",
            5,
            0.45,
            "good_till_canceled",
            posted_cycle,
        )

        assert len(prelog_calls) == 1
        assert prelog_calls[0]["response"]["client_order_id"] == expected_cid

    def test_maker_order_failure_logs_failed_row(self, monkeypatch):
        """Positive control: confirms the bookkeeping wiring actually
        differentiates outcomes, not just always writing 'pending' regardless
        of what place_maker_order does."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.side_effect = ConnectionError("boom")

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live, status FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 1
        assert row["status"] == "failed"

    def test_maker_order_status_unknown_not_failed(self, monkeypatch):
        """AUD-0007 applied to AUD-0010's fix: an ambiguous placement outcome
        through this call site must also land on 'unknown', not 'failed' --
        this is the sole live-order call site that previously had NO
        exception handling of any kind, so it's the highest-risk site to
        regress on this exact distinction."""
        import execution_log
        import main
        from kalshi_client import PROD_BASE, OrderStatusUnknownError

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.side_effect = OrderStatusUnknownError(
            "coid_qpb1", ConnectionError("timeout")
        )

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live, status, response FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 1
        assert row["status"] == "unknown"
        import json as _json

        assert _json.loads(row["response"])["client_order_id"] == "coid_qpb1"

    def test_maker_order_against_demo_client_logs_live_zero(self, monkeypatch):
        """Opus review follow-up (HIGH): a DEMO_BASE client reaches this
        branch too (the gate check only SKIPS the live-trading gate for
        demo, it doesn't block placement) -- the row must be logged
        live=0, not hardcoded live=True regardless of environment. A
        demo-mode order wrongly marked live=1 would count against the real
        daily live-spend cap, get polled against PROD by a live watch
        session, and could trigger a real prod SELL if it ever looked
        filled."""
        import execution_log
        import main
        from kalshi_client import DEMO_BASE

        mock_client = MagicMock()
        mock_client.base_url = DEMO_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.return_value = {
            "order_id": "ord_demo_1",
            "status": "resting",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        # is_daily_loss_halted(client) takes a client arg (main.py passes
        # client so the halt check includes unrealized MTM) -- a zero-arg
        # lambda here would TypeError and get silently swallowed by
        # _quick_paper_buy's own fail-open `except Exception: pass`, making
        # this mock fictional even though the test still passes today.
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 0


class TestCmdOrderLiveRiskGates:
    """Batch-22 item 1: _place_live_order (the automated live path) gates
    every entry on 3 execution_log-backed hard stops (daily live loss,
    daily live spend, max open live positions) in addition to the shared
    LiveTradingGate -- cmd_order (the manual live-order CLI path) had none
    of the three. Mirrors TestCmdOrderLiveRecording's gate-passing recipe;
    these tests are specifically about the 3 NEW checks, not the
    pre-existing LiveTradingGate (TestLiveTradingGate above) or
    check_position_limits (untouched by this fix)."""

    @contextmanager
    def _passing_gate_patches(self):
        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            yield

    def _mock_client(self):
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = None  # skip analysis branch
        return mock_client

    def _standard_setup(self, monkeypatch):
        import main

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    def test_daily_loss_limit_blocks_live_buy(self, monkeypatch, capsys):
        import main

        mock_client = self._mock_client()
        self._standard_setup(monkeypatch)
        monkeypatch.setattr(
            main, "_load_live_config", lambda: {"daily_loss_limit": 100.0}
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 150.0)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "daily live loss limit" in out
        assert "refusing" in out

    def test_daily_spend_cap_blocks_live_buy(self, monkeypatch, capsys):
        import main

        mock_client = self._mock_client()
        self._standard_setup(monkeypatch)
        monkeypatch.setattr(main, "_load_live_config", lambda: {})
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 600.0)
        # Opus review follow-up (F9): pin the cap explicitly rather than
        # relying on utils.MAX_DAILY_SPEND's ambient env-derived default --
        # main.py imports the name fresh from utils at call time, so
        # patching it there (not on order_executor, which has its own
        # separate binding) is what actually takes effect here.
        monkeypatch.setattr("utils.MAX_DAILY_SPEND", 500.0)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "daily live spend cap" in out
        assert "refusing" in out

    def test_max_open_positions_blocks_live_buy(self, monkeypatch, capsys):
        import main
        import order_executor

        mock_client = self._mock_client()
        self._standard_setup(monkeypatch)
        monkeypatch.setattr(
            main, "_load_live_config", lambda: {"max_open_positions": 3}
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 0.0)
        monkeypatch.setattr(order_executor, "_count_open_live_orders", lambda: 3)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "max open live positions" in out
        assert "refusing" in out

    def test_gates_pass_when_under_every_limit(self, monkeypatch):
        """Positive control (step 28): with every gate well under its
        limit, cmd_order must actually reach place_order -- proves the 3
        new checks aren't just always-refusing."""
        import main
        import order_executor

        mock_client = self._mock_client()
        mock_client.place_order.return_value = {
            "order_id": "ord_ok",
            "status": "executed",
            "fill_count_fp": "5.00",
        }
        self._standard_setup(monkeypatch)
        monkeypatch.setattr(
            main,
            "_load_live_config",
            lambda: {"daily_loss_limit": 100.0, "max_open_positions": 10},
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 0.0)
        monkeypatch.setattr(order_executor, "_count_open_live_orders", lambda: 0)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_called_once()

    def test_gates_do_not_apply_to_sell(self, monkeypatch, capsys):
        """The 3 new checks are ADDED-exposure caps (same reasoning as the
        check_position_limits scoping just below them in cmd_order) -- a
        live SELL must not be blocked by a daily-loss limit that's already
        exceeded, since blocking an exit is exactly backwards when the
        account most needs to reduce exposure."""
        import main

        mock_client = self._mock_client()
        mock_client.place_order.return_value = {
            "order_id": "ord_sell",
            "status": "executed",
            "fill_count_fp": "5.00",
        }
        self._standard_setup(monkeypatch)
        monkeypatch.setattr(
            main, "_load_live_config", lambda: {"daily_loss_limit": 1.0}
        )
        # Deliberately blown past every limit -- must not matter for a sell.
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 999.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 999.0)

        with self._passing_gate_patches():
            main.cmd_order(
                mock_client, "sell", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_called_once()
        out = capsys.readouterr().out.lower()
        assert "daily live loss limit" not in out
        assert "daily live spend cap" not in out


class TestQuickPaperBuyLiveRiskGates:
    """Batch-22 item 1 adjacency (confirmed via AskUserQuestion): main.py's
    _quick_paper_buy is a SECOND manual live-order path (its maker-order
    branch places a real order via place_maker_order when the client isn't
    demo) with the exact same 3-gate gap cmd_order had -- not cited by
    batch-22.md's own text, found while implementing item 1 for cmd_order.
    Mirrors TestCmdOrderLiveRiskGates' recipe for this call site."""

    @contextmanager
    def _passing_gate_patches(self):
        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            yield

    def _standard_inputs(self):
        return iter(
            [
                "KXTEST-25JUN01-T70",  # ticker
                "yes",  # side
                "2",  # order type: limit maker
                "0.45",  # limit price
                "5",  # qty
                "",  # thesis
            ]
        )

    def test_daily_loss_limit_blocks_live_maker_buy(self, monkeypatch, capsys):
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))
        monkeypatch.setattr(
            main, "_load_live_config", lambda: {"daily_loss_limit": 100.0}
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 150.0)

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "daily live loss limit" in out

    def test_daily_spend_cap_blocks_live_maker_buy(self, monkeypatch, capsys):
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))
        monkeypatch.setattr(main, "_load_live_config", lambda: {})
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 600.0)
        # Opus review follow-up (F9): see test_daily_spend_cap_blocks_live_buy's
        # matching comment.
        monkeypatch.setattr("utils.MAX_DAILY_SPEND", 500.0)

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "daily live spend cap" in out

    def test_max_open_positions_blocks_live_maker_buy(self, monkeypatch, capsys):
        import main
        import order_executor
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))
        monkeypatch.setattr(
            main, "_load_live_config", lambda: {"max_open_positions": 2}
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 0.0)
        monkeypatch.setattr(order_executor, "_count_open_live_orders", lambda: 2)

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_not_called()
        out = capsys.readouterr().out.lower()
        assert "max open live positions" in out

    def test_gates_pass_when_under_every_limit(self, monkeypatch):
        """Positive control (step 28): with every gate well under its
        limit, the maker order must actually be placed."""
        import main
        import order_executor
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = {}
        mock_client.place_maker_order.return_value = {
            "order_id": "ord_ok",
            "status": "resting",
        }
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda *_a, **_k: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
        monkeypatch.setattr(
            "paper.check_position_limits", lambda *a, **kw: {"ok": True}
        )
        _inputs = self._standard_inputs()
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))
        monkeypatch.setattr(
            main,
            "_load_live_config",
            lambda: {"daily_loss_limit": 100.0, "max_open_positions": 10},
        )
        monkeypatch.setattr("execution_log.get_today_live_loss", lambda: 0.0)
        monkeypatch.setattr("execution_log.get_today_live_spend", lambda: 0.0)
        monkeypatch.setattr(order_executor, "_count_open_live_orders", lambda: 0)

        with self._passing_gate_patches():
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_called_once()


class TestCmdOrderRainGuard:
    """Batch-22 item 5: every other shadow-only market family (hurricane-
    count, hurricane-next-event, storm-order, unsupported-hurricane, snow,
    hourly) has a direct refuse-outright guard in cmd_order -- rain had
    none, relying solely on paper.check_position_limits() (fail-open on
    exception, buy-only). Mirrors TestCmdOrderSnowGuard-style tests
    (tests/test_snow_markets.py) for the new rain guard."""

    def test_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        main.cmd_order(None, "buy", ["KXRAINNYCM-26AUG-5.0", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "rain" in out.lower()
        assert "RAIN_TRADING_ENABLED" in out

    def test_does_not_refuse_when_gate_active(self, monkeypatch):
        """Mutation-test proof the guard is real -- once _rain_gates_active()
        is True, cmd_order must proceed past THIS guard specifically (it may
        still stop later for unrelated reasons in this unit-test context,
        e.g. no real market to fetch)."""
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._rain_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(None, "buy", ["KXRAINNYCM-26AUG-5.0", "yes", "1", "0.10"])
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any("RAIN_TRADING_ENABLED" in p and "refusing" in p for p in printed)

    def test_refuses_when_gate_inactive_for_sell_too(self, monkeypatch, capsys):
        """Opus review follow-up (LOW #13): item 5's own stated gap was
        explicitly that 'a manual live SELL of a rain ticker was entirely
        unguarded' -- the guard itself is action-agnostic (runs before any
        buy/sell branching), but nothing pinned the sell half with its own
        regression test."""
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        main.cmd_order(None, "sell", ["KXRAINNYCM-26AUG-5.0", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "rain" in out.lower()
        assert "RAIN_TRADING_ENABLED" in out
