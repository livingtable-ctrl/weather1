"""P0-2: LiveTradingGate must block live orders when graduation/safety gates fail."""

import os
from contextlib import contextmanager
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
        independent of _is_live's own recording branch."""
        fake_market = {
            "ticker": "KXHIGH-NYC-26APR17-T70",
            "close_time": "2026-04-17T20:00:00Z",
        }
        fake_enriched = dict(fake_market, _city="NYC", _date=None)
        fake_analysis = {
            "forecast_prob": 0.65,
            "market_prob": 0.50,
            "net_edge": 0.10,
            "kelly": 0.05,
            "method": "ensemble",
            "days_out": 1,
            "target_date": "2026-04-17",
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
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
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
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
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

        with (
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
        ):
            main.cmd_order(
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT live FROM orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["live"] == 0
        trades = paper.get_all_trades()
        assert len(trades) == 1
        assert trades[0]["ticker"] == "KXHIGH-NYC-26APR17-T70"
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
        # gross_pnl = 10 * (0.60 - 0.40) = 2.00; gain -> fee applies:
        # 2.00 * (1 - 0.07) = 1.86
        assert position_row["pnl"] == pytest.approx(1.86)
        assert exit_row["live"] == 1
        assert exit_row["closes_position_id"] == position_id
        # Must not also open a phantom NEW paper position at the sell price
        # -- the exact bug class this fix resolves.
        assert paper.get_all_trades() == []

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

    def test_live_order_placed_immediate_or_cancel(self, monkeypatch):
        """Opus review (2026-08-17): live orders must be placed IOC, not the
        GTC default -- a resting order has no path back to being recognized
        as a manageable position (no code teaches the general poller about
        closes_position_id), which would silently orphan the fix. Confirmed
        via AskUserQuestion as the deliberate trading-behavior tradeoff."""
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

    def test_demo_order_stays_good_till_canceled(self, monkeypatch):
        """Positive control for the test above: demo/paper mode keeps the
        prior GTC default -- only the live path's order semantics change."""
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
                mock_client, "buy", ["KXHIGH-NYC-26APR17-T70", "yes", "5", "0.40"]
            )

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT close_time, entry_prob, forecast_cycle FROM orders "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["close_time"] == fake_market["close_time"]
        assert row["entry_prob"] == pytest.approx(fake_analysis["forecast_prob"])
        assert row["forecast_cycle"] is not None


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
