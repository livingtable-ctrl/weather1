"""Tests for live execution path in main.py."""

import pytest


def _live_gates_open():
    """Patch BOTH live gates open, for a test that only cares about the code
    path past them.

    Batch-58 item 4 split the single live gate in two: _exit_live_position
    now calls trading_gates.pre_live_exit_check (the reduced gate that a
    risk-REDUCING order runs) while every other live-order path still calls
    pre_live_trade_check. Tests that just need "assume the gate permits this
    order" patch both, so a caller moving between the two can never silently
    turn one of these tests into a no-op against an unpatched real gate.

    Tests that assert a gate BLOCKS something deliberately do not use this --
    they patch the one specific gate their path is supposed to consult.
    """
    from unittest.mock import MagicMock, patch

    return patch.multiple(
        "trading_gates",
        pre_live_trade_check=MagicMock(return_value=None),
        pre_live_exit_check=MagicMock(return_value=None),
    )


def _batched_lookup(order, uncertain=False):
    """side_effect for a mock client's _find_orders_by_client_ids.

    Batch-58 item 6 hoisted _recover_pending_orders' per-row
    client._find_order_by_client_id() call out of the loop and replaced it
    with ONE client._find_orders_by_client_ids(set_of_ids) call per recovery
    pass. These tests previously stubbed the per-row form; they now stub the
    batched one, returning `order` as the match for every id the code asks
    about (each of these tests exercises exactly one unknown row, so
    "matches everything asked for" and "matches this row" are the same
    thing). Pass order=None for the not-found case.
    """

    def _impl(client_order_ids):
        matches = {} if order is None else {c: order for c in client_order_ids}
        return matches, uncertain

    return _impl


class TestMidpointPrice:
    """_midpoint_price is still used for live order placement/repricing
    (order_executor._place_live_order, _reprice_or_cancel_pending_orders) --
    out of scope for the model-exit pricing-convention fix. main.py no longer
    re-exports it since its one exit-path use (the manual close menu) now
    uses _liquidation_price instead."""

    def test_midpoint_yes_side(self):
        from order_executor import _midpoint_price

        market = {"yes_bid": 45, "yes_ask": 55}
        assert _midpoint_price(market, "yes") == pytest.approx(0.50)

    def test_midpoint_no_side(self):
        from order_executor import _midpoint_price

        market = {"yes_bid": 45, "yes_ask": 55}
        # no_bid = 100 - yes_ask = 45; no_ask = 100 - yes_bid = 55 → midpoint = 0.50
        assert _midpoint_price(market, "no") == pytest.approx(0.50)


class TestLoadLiveConfig:
    def test_creates_default_if_missing(self, tmp_path, monkeypatch):
        import main

        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", tmp_path / "live_config.json")
        cfg = main._load_live_config()
        assert cfg["max_trade_dollars"] == 50
        assert cfg["daily_loss_limit"] == 200
        assert cfg["max_open_positions"] == 10
        assert (tmp_path / "live_config.json").exists()

    def test_oserror_creating_default_falls_back_to_in_memory_defaults(
        self, tmp_path, monkeypatch
    ):
        """M-C (opus review): the FileNotFoundError branch's own mkdir()/
        write_text() can raise OSError (read-only dir, disk full, AV lock) --
        a NEW exception distinct from the one being handled, so the sibling
        `except OSError` clause (which only wraps the original open() call)
        can't catch it. Must fall back to in-memory defaults, not propagate,
        for the same cmd_watch-loop reason M-26 exists. Mutation-tested:
        removing the inner try/except around mkdir()/write_text() makes this
        raise PermissionError instead of returning defaults."""
        from pathlib import Path

        import main

        missing_path = tmp_path / "live_config.json"
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", missing_path)
        monkeypatch.setattr(
            Path,
            "mkdir",
            lambda self, *a, **kw: (_ for _ in ()).throw(
                PermissionError("simulated read-only data dir")
            ),
        )

        cfg = main._load_live_config()  # must not raise

        assert cfg["daily_loss_limit"] == 200
        assert not missing_path.exists()

    def test_partial_file_merges_over_defaults(self, tmp_path, monkeypatch):
        """M-26: a valid-JSON file missing daily_loss_limit must NOT make
        callers' `.get("daily_loss_limit", float("inf"))` fail open -- the
        merge must fill it in from _LIVE_CONFIG_DEFAULT.

        Round-2 opus review (M2-8) correction: the docstring here used to
        claim a specific mutation (reverting to `return loaded`) that no
        longer exists in the current code -- M-D replaced the plain-dict
        merge with a per-key validation loop (main.py's _load_live_config).
        That loop is deliberately REDUNDANT in two independent ways (both
        `merged = dict(_LIVE_CONFIG_DEFAULT)`'s pre-seeded base AND each
        iteration's own `loaded.get(_key, _default_val)` fallback separately
        guarantee "missing key -> default"), verified by mutating each one
        individually -- neither alone breaks this test. This test still
        pins real, correct, non-vacuous end-to-end behavior (confirmed via
        the explicit-value-preserved assertion below, which WOULD fail if
        the loop stopped reading `loaded` at all), it just isn't a minimal
        single-line mutation target given the current implementation's
        intentional redundancy."""
        import json

        import main

        cfg_path = tmp_path / "live_config.json"
        cfg_path.write_text(json.dumps({"max_trade_dollars": 75}))
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", cfg_path)

        cfg = main._load_live_config()
        assert cfg["max_trade_dollars"] == 75  # explicit value preserved
        assert cfg["daily_loss_limit"] == 200  # missing key filled from default
        assert cfg["max_open_positions"] == 10
        assert cfg["gtc_cancel_hours"] == 24

    def test_null_daily_loss_limit_falls_back_to_default_not_none(
        self, tmp_path, monkeypatch
    ):
        """M-D (opus review): a PRESENT-but-null value must also fall back to
        the safe default, not just an ABSENT one -- the plain dict merge
        (`{**DEFAULT, **loaded}`) only fixes missing keys; `{"daily_loss_
        limit": null}` would overwrite 200 with None and TypeError on the
        first numeric comparison in the live-order path this exists to
        protect. Mutation-tested: reverting to the plain merge makes
        cfg["daily_loss_limit"] be None instead of 200."""
        import json

        import main

        cfg_path = tmp_path / "live_config.json"
        cfg_path.write_text(
            json.dumps({"daily_loss_limit": None, "max_trade_dollars": "not-a-number"})
        )
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", cfg_path)

        cfg = main._load_live_config()
        assert cfg["daily_loss_limit"] == 200
        assert cfg["max_trade_dollars"] == 50  # non-numeric string also rejected
        assert cfg["max_open_positions"] == 10  # untouched key still present

    def test_nan_daily_loss_limit_falls_back_to_default(self, tmp_path, monkeypatch):
        """M2-3 (round-2 opus review): json.load() accepts bare NaN/Infinity
        as real Python floats (a non-standard-JSON extension) -- the M-D type
        gate's `isinstance(_val, int | float)` alone let `{"daily_loss_
        limit": NaN}` through, and every consumer's gate is `live_loss >=
        daily_loss_limit`, which is always False against NaN -- silently
        disabling the circuit breaker instead of failing safe. Mutation-
        tested: removing the `math.isfinite(_val)` clause makes
        cfg["daily_loss_limit"] be NaN instead of 200 (assertable via
        `!= itself`, since NaN != NaN)."""

        import main

        cfg_path = tmp_path / "live_config.json"
        cfg_path.write_text('{"daily_loss_limit": NaN, "max_trade_dollars": Infinity}')
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", cfg_path)

        cfg = main._load_live_config()
        assert cfg["daily_loss_limit"] == 200
        assert cfg["max_trade_dollars"] == 50

    def test_non_dict_json_falls_back_to_defaults(self, tmp_path, monkeypatch):
        """M-26: valid JSON that isn't an object (e.g. a list) must be
        rejected explicitly, not returned as-is (a caller's .get() would
        raise AttributeError on a list)."""
        import json

        import main

        cfg_path = tmp_path / "live_config.json"
        cfg_path.write_text(json.dumps([1, 2, 3]))
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", cfg_path)

        cfg = main._load_live_config()
        assert cfg == {
            "max_trade_dollars": 50,
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }

    def test_transient_oserror_falls_back_to_defaults_not_raises(
        self, tmp_path, monkeypatch
    ):
        """M-26: a transient OSError (AV-scan PermissionError, a Windows
        sharing violation) must not propagate -- this is called every cycle
        inside cmd_watch's persistent while-True loop, whose only exception
        handler is `except KeyboardInterrupt` (AUD-0008's failure mode).
        Mutation-tested: removing the `except OSError` branch makes this
        raise PermissionError instead of returning defaults."""
        import builtins

        import main

        cfg_path = tmp_path / "live_config.json"
        cfg_path.write_text("{}")
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", cfg_path)

        real_open = builtins.open

        def _flaky_open(path, *a, **kw):
            if str(path) == str(cfg_path):
                raise PermissionError("simulated AV-scan lock")
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", _flaky_open)

        cfg = main._load_live_config()
        assert cfg["daily_loss_limit"] == 200


class TestPlaceLiveOrder:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_daily_loss_limit_blocks_after_db_loss(self):
        """Daily loss limit blocks order when DB-backed loss is at or above limit."""
        import execution_log
        import main

        # Seed today's loss at the limit
        execution_log.add_live_loss(100.0)

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 100,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        placed, cost = main._place_live_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            analysis={
                "kelly_quantity": 2,
                "implied_prob": 0.55,
                "market": {"yes_bid": 50, "yes_ask": 60},
            },
            config=config,
            client=None,
            cycle="12z",
        )
        assert placed is False
        assert cost == 0.0

    def test_daily_live_spend_cap_blocks_across_cycles(self, monkeypatch):
        """Deep-review followup: F7 removed placement-time add_live_loss(cost)
        (correctly, it double-counted with settlement-time add_live_loss(-pnl)),
        but that call had also been the only cross-cycle brake on live spend --
        _daily_paper_spend()/_daily_sameday_spend() never see live orders.
        A long-running `watch --auto --live` session (5-min loop) would
        otherwise reset its live-spend view to $0 every cycle. Confirm a
        prior cycle's already-logged live spend (simulating an earlier
        iteration of the same session) blocks a new placement that would
        otherwise succeed, via the dedicated spend counter -- and that the
        API is never even called once the cap is reached. Bypasses every
        OTHER gate (trading gate, cycle dedup, open-position count) so the
        new spend cap is the sole thing under test -- proven by first
        confirming the identical setup places successfully with the cap
        raised."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor

        # Simulate a live order placed in an earlier watch cycle this same
        # UTC day: 20 contracts @ $0.55 = $11.00.
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T70",
            side="yes",
            quantity=20,
            price=0.55,
            status="filled",
            live=True,
        )

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 1000,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 2,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            # Control: with a cap well above the already-logged $11.00, this
            # exact setup must succeed -- proves the block below is really
            # the spend cap, not some other gate this test forgot to mock.
            monkeypatch.setattr(
                order_executor, "MAX_DAILY_SPEND", 1000.0, raising=False
            )
            placed_ok, cost_ok = order_executor._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )
            assert placed_ok is True, "control case must place — setup is broken"
            assert cost_ok > 0.0

            mock_client.reset_mock()
            monkeypatch.setattr(order_executor, "MAX_DAILY_SPEND", 10.0, raising=False)
            placed, cost = order_executor._place_live_order(
                ticker="KXHIGH-25MAY15-T76",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is False
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_daily_loss_limit_blocks_without_keyerror_when_key_missing(self):
        """F10: config['daily_loss_limit'] was bare-indexed in the print on
        the same branch as a .get()-defaulted comparison — reachable when
        get_today_live_loss() fails closed to inf (degraded-DB path) and the
        config has no daily_loss_limit key at all. Must skip cleanly, not
        raise KeyError."""
        import execution_log
        import main

        # _degraded_flag_path() is DB_PATH.parent / "..." — DB_PATH.parent is
        # the shared system temp dir here, so this flag must be cleared even
        # on assertion failure or it leaks into unrelated tests.
        execution_log._set_degraded_flag("test")  # forces get_today_live_loss() -> inf
        try:
            config = {
                "max_trade_dollars": 50,
                "max_open_positions": 10,
                "gtc_cancel_hours": 24,
            }
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis={
                    "kelly_quantity": 2,
                    "implied_prob": 0.55,
                    "market": {"yes_bid": 50, "yes_ask": 60},
                },
                config=config,
                client=None,
                cycle="12z",
            )
            assert placed is False
            assert cost == 0.0
        finally:
            execution_log._clear_degraded_flag()

    def test_max_trade_dollars_caps_size(self):
        """Kelly wants 10 contracts at $0.55 = $5.50/contract → $55 total, capped to $50."""
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_abc123",
            "status": "resting",
        }

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 10,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
            "edge": 0.25,
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("execution_log.log_order", return_value=1),
            # Opus review follow-up: _place_live_order lives in
            # order_executor.py and resolves this name from ITS OWN module
            # globals, not main's -- patching main._count_open_live_orders
            # was inert (the real function always ran, harmlessly returning
            # 0 against this test's empty DB either way).
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is True
        # price = midpoint(50, 60) = 0.55; Kelly qty 10 × $0.55 = $5.50 < $50 cap → 10 contracts
        assert mock_client.place_order.called
        assert cost > 0.0
        call_args = mock_client.place_order.call_args
        assert call_args.kwargs["price"] == pytest.approx(0.55)

    def test_missing_max_trade_dollars_refuses_rather_than_crashes(self):
        """Batch-31 L-10(b): steps 1/1b/2 all defensively .get() this same
        hand-editable config dict, but the size-computation step used a bare
        config["max_trade_dollars"] subscript -- an uncaught KeyError instead
        of a clean skip if the key were ever missing. Must fail closed (skip
        the trade, quantity capped to 0) rather than falling back to an
        unbounded/large default that would size the trade unbounded."""
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        mock_client = MagicMock()
        config = {
            # max_trade_dollars deliberately omitted.
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 10,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
            "edge": 0.25,
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is False
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_order_status_unknown_logs_unknown_not_failed(self):
        """AUD-0007: when place_order() raises OrderStatusUnknownError (POST
        failed AND reconciliation itself couldn't confirm either way), the
        row must be logged status='unknown', never 'failed' -- every dedup
        guard in execution_log.py excludes 'failed', so misclassifying an
        ambiguous outcome as 'failed' would let a real live position go
        untracked and be re-orderable."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import main
        import order_executor
        from kalshi_client import OrderStatusUnknownError

        mock_client = MagicMock()
        mock_client.place_order.side_effect = OrderStatusUnknownError(
            "coid_abc123", ConnectionError("timeout")
        )

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 5,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            # Opus review follow-up: _place_live_order lives in
            # order_executor.py and resolves this name from ITS OWN module
            # globals, not main's -- patching main._count_open_live_orders
            # was inert (the real function always ran, harmlessly returning
            # 0 against this test's empty DB either way).
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is False
        assert cost == 0.0
        unknown_rows = execution_log.get_unknown_live_orders()
        assert len(unknown_rows) == 1
        assert unknown_rows[0]["ticker"] == "KXHIGH-25MAY15-T75"
        import json as _json

        stored_response = _json.loads(unknown_rows[0]["response"])
        assert stored_response["client_order_id"] == "coid_abc123"

        # Positive control: a genuinely-failed (not ambiguous) order must
        # still land in 'failed', not 'unknown' -- proves the two except
        # branches are actually distinguished, not that every order lands
        # in 'unknown' regardless of exception type.
        mock_client.place_order.side_effect = ConnectionError("plain failure")
        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            # Opus review follow-up: _place_live_order lives in
            # order_executor.py and resolves this name from ITS OWN module
            # globals, not main's -- patching main._count_open_live_orders
            # was inert (the real function always ran, harmlessly returning
            # 0 against this test's empty DB either way).
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            main._place_live_order(
                ticker="KXHIGH-25MAY15-T76",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )
        failed_row = next(
            o
            for o in execution_log.get_recent_orders(limit=10)
            if o["ticker"] == "KXHIGH-25MAY15-T76"
        )
        assert failed_row["status"] == "failed"
        assert execution_log.get_unknown_live_orders() == unknown_rows


class TestAutoPlaceTradesCycleCheck:
    def test_cycle_dedup_skips_already_ordered(self, monkeypatch):
        """If was_ordered_this_cycle returns True, no paper or live order is placed."""
        from unittest.mock import patch

        import main

        # Construct opp with the real field names _auto_place_trades checks:
        # net_signal must contain "STRONG", time_risk must not be "HIGH",
        # ci_adjusted_kelly must be large enough to produce qty >= 1,
        # market_prob used as entry_price.
        opp = {
            "ticker": "KXHIGH-25MAY15-T75",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.50,
            "market_prob": 0.55,
            "_city": "Houston",
            "_date": None,
        }

        mock_open_trades = []

        with (
            patch("paper.get_open_trades", return_value=mock_open_trades),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=True),
            patch("main.place_paper_order") as mock_paper,
            patch("main._place_live_order") as mock_live,
        ):
            main._auto_place_trades([opp], client=None, live=False, live_config=None)

        mock_paper.assert_not_called()
        mock_live.assert_not_called()


class TestOpenTradesListLivePath:
    """F6: _open_trades_list.append(trade) only ever ran on the paper branch.
    A live placement earlier in the same cron cycle was invisible to later
    candidates' VaR/correlation checks — each got scored as if it were the
    first position in the portfolio."""

    def test_live_placement_appends_to_open_trades_list(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        monkeypatch.setattr(order_executor, "MAX_VAR_DOLLARS", 1000.0, raising=False)

        var_calls: list[list] = []

        def _fake_portfolio_var(trades):
            var_calls.append(list(trades))
            return 0.0  # well under the cap — never blocks placement

        import time as _time

        def _opp(ticker: str, city: str) -> dict:
            return {
                "ticker": ticker,
                "net_signal": "STRONG_BUY",
                "time_risk": "LOW",
                "recommended_side": "yes",
                "ci_adjusted_kelly": 0.50,
                "market_prob": 0.55,
                "forecast_prob": 0.70,
                "net_edge": 0.20,
                "edge": 0.20,
                "model_consensus": True,
                "data_fetched_at": _time.time(),
                "yes_bid": 53,
                "yes_ask": 57,
                "_city": city,
                "_date": None,
                # Multi-day opp: this is the live path re-opened by dropping
                # the GFS lockout gate (backlog.txt "GFS_LOCKOUT_MINS=90
                # DOESN'T MATCH REAL GFS PROPAGATION DELAY" -- the gate used
                # to block days_out>=1 trades for ~25% of every day).
                "days_out": 1,
            }

        opp1 = _opp("KXHIGH-A", "Houston")
        opp2 = _opp("KXHIGH-B", "Austin")
        live_config = {
            "daily_loss_limit": 500,
            "max_open_positions": 10,
            "max_trade_dollars": 100,
        }
        client = MagicMock()
        client.get_market.side_effect = ConnectionError("no live fetch in test")

        with (
            patch("paper.get_open_trades", return_value=[]),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("monte_carlo.portfolio_var", side_effect=_fake_portfolio_var),
            patch.object(order_executor, "_resolve_live_balance", return_value=0.0),
            patch.object(order_executor, "_place_live_order", return_value=(True, 5.0)),
        ):
            main._auto_place_trades(
                [opp1, opp2], client=client, live=True, live_config=live_config
            )

        assert len(var_calls) == 2, (
            f"expected one VaR check per opp, got {len(var_calls)}"
        )
        assert len(var_calls[1]) == len(var_calls[0]) + 1, (
            "the second opp's VaR check must see the first live trade placed "
            "earlier this same cycle — it was invisible before this fix"
        )


class TestVarGateFailsClosed:
    """F5: a portfolio_var() exception used to be swallowed at DEBUG and the
    trade placed anyway — the flash-crash check in this same file explicitly
    fails closed on its own internal errors; the VaR gate now matches."""

    def test_var_computation_error_skips_the_trade(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        monkeypatch.setattr(order_executor, "MAX_VAR_DOLLARS", 1000.0, raising=False)

        import time as _time

        opp = {
            "ticker": "KXHIGH-A",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.50,
            "market_prob": 0.55,
            "forecast_prob": 0.70,
            "net_edge": 0.20,
            "edge": 0.20,
            "model_consensus": True,
            "data_fetched_at": _time.time(),
            "yes_bid": 53,
            "yes_ask": 57,
            "_city": "Houston",
            "_date": None,
        }

        placed = []
        with (
            patch("paper.get_open_trades", return_value=[]),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch(
                "monte_carlo.portfolio_var",
                side_effect=RuntimeError("simulation blew up"),
            ),
            patch.object(
                order_executor,
                "place_paper_order",
                side_effect=lambda *a, **kw: placed.append(1) or {"id": 1},
            ),
        ):
            main._auto_place_trades([opp], client=MagicMock(), live=False)

        assert not placed, (
            "a VaR computation error must skip the trade (fail closed), not "
            "place it as if the check had passed"
        )


class TestRecoverPendingOrders:
    """2026-07-09: Kalshi's real order-status enum is resting/canceled/executed
    -- there is no "filled" or "expired". _recover_pending_orders previously
    checked api_status in ("filled", "canceled", "expired"), so a genuinely
    executed order fell through to the "unknown API status -- leaving
    pending" branch and was never resolved."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_executed_order_resolves_to_internal_filled_status(self):
        """A pending row whose order actually executed must resolve to this
        bot's internal 'filled' term, not be left stuck on 'pending'."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc123"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_abc123",
            "status": "executed",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"

    def test_canceled_order_resolves_to_canceled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_xyz"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_xyz",
            "status": "canceled",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "canceled"

    def test_partial_fill_then_cancel_resolves_to_filled(self):
        """F9: Kalshi has no distinct 'partially filled' status -- an order
        that fills some contracts and then gets canceled for the remainder
        reports status="canceled" with a nonzero fill_count_fp. That must
        resolve to 'filled' (not 'canceled') so it still reaches
        get_filled_unsettled_live_orders() and gets settled; otherwise a
        real, live exchange position is silently dropped and never counted
        toward P&L."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_partial"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_partial",
            "status": "canceled",
            "fill_count_fp": "2.00",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 2

    def test_resting_order_resolves_to_pending(self):
        """A resting order must land on status='pending' — the only status
        every downstream consumer (fill polling, GTC cancel, max_open_positions,
        PnL summary) actually filters on. F1: 'placed' was a dead-end status
        invisible to all of them."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_rest"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_rest",
            "status": "resting",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "pending"

    def test_resting_order_recovery_preserves_response_for_fill_polling(self):
        """Deep-review followup: log_order_result() does an unconditional
        column UPDATE, so a resting->pending recovery call that omits
        response= overwrites the stored order_id with NULL.
        _poll_pending_orders' own pending-row filter requires
        o.get("response") (line ~350) -- without it, a crash-recovered
        resting order becomes permanently invisible to fill polling,
        pre-close cancel, and the GTC-age cancel, silently re-orphaning the
        exact order this recovery path exists to reattach to the
        lifecycle."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _poll_pending_orders, _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_rest2"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_rest2",
            "status": "resting",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["response"] is not None, (
            "response was wiped to NULL by the recovery UPDATE, erasing order_id"
        )

        # Now confirm the row is actually still reachable by fill polling.
        mock_client.get_order.return_value = {
            "order_id": "ord_rest2",
            "status": "executed",
            "fill_count_fp": "2.00",
        }
        _poll_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled", (
            "order became invisible to _poll_pending_orders after recovery "
            "nulled its response/order_id"
        )


class TestReconcileLivePositions:
    """AUD-0025: no automated code path ever cross-checked execution_log's
    internally-tracked live positions against Kalshi's own ground truth
    (GET /portfolio/positions) -- the only caller of client.get_positions()
    was a manual CLI display command (output_formatters.cmd_positions).
    Log-only: this never corrects anything, it just makes drift visible."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _log_filled_position(self, ticker):
        import execution_log

        row_id = execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_" + ticker},
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=2)
        return row_id

    def test_no_drift_does_not_log_a_warning(self, caplog):
        import logging
        from unittest.mock import MagicMock

        from order_executor import _reconcile_live_positions

        self._log_filled_position("KXHIGH-25MAY15-T75")

        mock_client = MagicMock()
        mock_client.get_positions.return_value = [
            {"ticker": "KXHIGH-25MAY15-T75", "position": 2}
        ]

        with caplog.at_level(logging.WARNING, logger="order_executor"):
            _reconcile_live_positions(mock_client)

        assert not any("drift" in r.message for r in caplog.records), (
            "matching positions on both sides must not log a drift warning"
        )

    def test_tracked_but_not_on_exchange_logs_warning(self, caplog):
        """Simulates a position execution_log believes is still open but
        Kalshi's own ledger no longer shows (e.g. closed by hand on the
        Kalshi UI, bypassing this bot entirely)."""
        import logging
        from unittest.mock import MagicMock

        from order_executor import _reconcile_live_positions

        self._log_filled_position("KXHIGH-25MAY15-T75")

        mock_client = MagicMock()
        mock_client.get_positions.return_value = []

        with caplog.at_level(logging.WARNING, logger="order_executor"):
            _reconcile_live_positions(mock_client)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("KXHIGH-25MAY15-T75" in r.message for r in warnings), (
            "a position tracked here but missing from Kalshi must log a warning"
        )

    def test_on_exchange_but_untracked_logs_warning(self, caplog):
        """Simulates the opposite drift direction: a real exchange position
        execution_log has no row for at all (e.g. a crash-recovery gap this
        gate exists as a backstop for)."""
        import logging
        from unittest.mock import MagicMock

        from order_executor import _reconcile_live_positions

        mock_client = MagicMock()
        mock_client.get_positions.return_value = [
            {"ticker": "KXHIGH-25MAY15-T99", "position": -3}
        ]

        with caplog.at_level(logging.WARNING, logger="order_executor"):
            _reconcile_live_positions(mock_client)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("KXHIGH-25MAY15-T99" in r.message for r in warnings), (
            "a position on the exchange but untracked here must log a warning"
        )

    def test_zero_position_on_exchange_is_not_counted_as_held(self, caplog):
        """A ticker with position=0 in the API response (fully flat) must
        not be treated as a real held position -- otherwise it would falsely
        manufacture drift against execution_log's own (empty) tracking."""
        import logging
        from unittest.mock import MagicMock

        from order_executor import _reconcile_live_positions

        mock_client = MagicMock()
        mock_client.get_positions.return_value = [
            {"ticker": "KXHIGH-25MAY15-T75", "position": 0}
        ]

        with caplog.at_level(logging.WARNING, logger="order_executor"):
            _reconcile_live_positions(mock_client)

        assert not any("drift" in r.message for r in caplog.records), (
            "a zero-position row must not be treated as a real exchange position"
        )

    def test_client_get_positions_failure_does_not_raise(self, caplog):
        """Opus review (round 1): the function's own docstring claims it
        never raises, but the original code had no internal guard -- only
        the CALLER's try/except delivered that. Verify the function itself
        is safe when called directly, with no caller wrapper at all."""
        import logging
        from unittest.mock import MagicMock

        from order_executor import _reconcile_live_positions

        mock_client = MagicMock()
        mock_client.get_positions.side_effect = RuntimeError("Kalshi API down")

        with caplog.at_level(logging.WARNING, logger="order_executor"):
            _reconcile_live_positions(mock_client)  # must not raise

        assert any("lookup failed" in r.message for r in caplog.records), (
            "a lookup failure should be logged, not silently swallowed"
        )


class TestRecoverUnknownOrders:
    """AUD-0007: 'unknown' rows (place_order()'s POST failed AND
    reconciliation itself couldn't confirm either way) have no order_id --
    only a client_order_id stashed in response at write time -- so they need
    a distinct re-check path from the order_id-based 'pending' loop above.
    _recover_pending_orders() (despite its name, unchanged for backwards
    compat with its many existing call sites) now handles both."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_found_on_recheck_resolves_to_filled(self):
        """An 'unknown' row whose order turns out to have actually landed
        (found this time via client_order_id) must resolve to 'filled', not
        stay stuck 'unknown' forever."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_recheck1"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {"order_id": "ord_found", "status": "executed", "fill_count_fp": "2.00"},
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 2
        mock_client._find_orders_by_client_ids.assert_called_once_with(
            {"coid_recheck1"}
        )

    def test_confirmed_not_found_resolves_to_failed(self):
        """An 'unknown' row where reconciliation NOW genuinely completes
        (uncertain=False) and confirms no matching order exists is safe to
        finally mark 'failed' -- dedup guards correctly unblock a retry."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_recheck2"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            None, False
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "failed"

    def test_confirmed_not_found_exit_order_releases_the_position_claim(self):
        """Independent review (batch-31 F4): a confirmed-failed 'unknown'
        row that was a protective EXIT attempt (closes_position_id set)
        definitively means that SELL never landed -- the same
        confirmed-not-landed condition _exit_live_position's own generic-
        Exception branch already releases the exit claim for. Without this,
        the position would sit exit-claim-blocked until the TTL expires
        despite being provably unprotected right now."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        claim_token = execution_log.claim_position_for_exit(position_id)
        assert claim_token is not None

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_exit_recheck"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            None, False
        )

        _recover_pending_orders(mock_client)

        # The claim must be gone -- a fresh claim attempt now succeeds.
        assert execution_log.claim_position_for_exit(position_id) is not None

    def test_confirmed_not_found_exit_order_does_not_release_a_newer_claim(self):
        """Positive control / F5-style guard for the fix above: if the
        ORIGINAL exit attempt this recovery pass is resolving is old enough
        that its own claim could plausibly have expired and been replaced,
        and a DIFFERENT scanner has in fact since won a fresh claim on the
        same position, recovery must not wipe that active, newer claim out
        from under it. Timeline matters here -- both the original exit
        row's placed_at AND the original claim must be backdated together
        (mirroring a real ~11-minutes-ago attempt), otherwise the fix's own
        recency heuristic can't distinguish this from the position's normal
        very-first claim in the test above."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        eleven_min_ago = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        execution_log.claim_position_for_exit(position_id)
        exit_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_exit_recheck_2"},
        )
        # Backdate both the original claim and this exit row's own placed_at
        # to the same ~11-minutes-ago moment, matching a real attempt whose
        # claim has since gone TTL-eligible.
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET exit_claimed_at = ? WHERE id = ?",
                (eleven_min_ago, position_id),
            )
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?",
                (eleven_min_ago, exit_row_id),
            )
        # A different scanner now wins a fresh claim on the same position.
        new_token = execution_log.claim_position_for_exit(position_id, ttl_minutes=10)
        assert new_token is not None

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            None, False
        )

        _recover_pending_orders(mock_client)

        # The NEW claimant's still-active claim must survive untouched.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_claimed_at FROM orders WHERE id = ?", (position_id,)
            ).fetchone()
        assert row["exit_claimed_at"] == new_token

    def test_still_uncertain_stays_unknown(self):
        """Positive control for the two tests above: if reconciliation is
        STILL uncertain (e.g. the API is still degraded), the row must stay
        'unknown' rather than being force-resolved either way -- proves this
        recovery pass doesn't just resolve every unknown row unconditionally
        regardless of what the re-check actually found."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_recheck3"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "unknown"

    def test_recovered_exit_order_settles_the_position_it_closed(self):
        """Opus review follow-up (HIGH): resolving a recovered 'unknown'
        EXIT order's own status to 'filled' is not enough -- unlike
        _exit_live_position (the live path this mirrors), the position it
        closed must also be settled (record_live_exit_fill), or it stays
        open forever: still returned by get_filled_unsettled_live_orders()
        even though it was genuinely sold, so the exit scanner would keep
        placing fresh real SELL orders against it every cycle, and its true
        P&L would never reach the tax CSV / PnL summary."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,  # entry price
            status="filled",
            live=True,
        )
        exit_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,  # exit price
            order_type="market",
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_exit_recover"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_exit_found",
                "status": "executed",
                "fill_count_fp": "10.00",
            },
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        exit_row = next(o for o in orders if o["id"] == exit_row_id)
        assert exit_row["status"] == "filled"

        position_row = next(o for o in orders if o["id"] == position_id)
        assert position_row["settled_at"] is not None, (
            "the position the recovered exit order closed was never "
            "settled -- it will look open forever to get_filled_unsettled_"
            "live_orders(), triggering repeat real sell attempts"
        )
        # Batch-22 items 3+6: gross_pnl = 10 * (0.20 - 0.40) = -2.00; fee
        # (utils.kalshi_taker_fee) applies regardless of win/loss:
        # ceil(0.07*10*0.20*0.80*100)/100 = 0.12. pnl = -2.00 - 0.12 = -2.12.
        assert position_row["pnl"] == pytest.approx(-2.12)
        assert position_row["exit_reason"] == "recovered_exit"

    def test_recovered_exit_partial_fill_settles_partial_and_leaves_position_open(
        self,
    ):
        """Partial-fill counterpart: the position must be REDUCED (not
        fully settled), and the exit order's own row gets its own pnl
        recorded separately -- mirrors _exit_live_position's partial-fill
        branch exactly."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        exit_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_partial_recover"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_partial_found",
                "status": "canceled",
                "fill_count_fp": "4.00",  # 4 of 10 filled before cancel (F9)
            },
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        exit_row = next(o for o in orders if o["id"] == exit_row_id)
        # F9: canceled + nonzero fill_count -> internal 'filled'.
        assert exit_row["status"] == "filled"
        assert exit_row["settled_at"] is not None, (
            "the exit order's OWN row must be settled with its own pnl for "
            "a partial fill (record_live_early_exit), same as _exit_live_"
            "position's partial-fill branch"
        )
        # gross_pnl = 4 * (0.20 - 0.40) = -0.80; fee = ceil(0.07*4*0.20*
        # 0.80*100)/100 = 0.05. pnl = -0.80 - 0.05 = -0.85.
        assert exit_row["pnl"] == pytest.approx(-0.85)

        position_row = next(o for o in orders if o["id"] == position_id)
        assert position_row["settled_at"] is None, (
            "a partial exit must leave the position OPEN at its reduced "
            "size, not fully settle it"
        )
        assert position_row["fill_quantity"] == 6  # 10 - 4 remaining

    def test_settlement_failure_reverts_to_unknown_not_permanently_filled(self):
        """Opus review follow-up (round 2, HIGH): round 1 wrote the exit
        row's own status to 'filled' BEFORE attempting to settle the
        position it closed -- a settlement failure (e.g. a locked DB) was
        then PERMANENT, because get_unknown_live_orders() only selects
        status='unknown', so a row that already left that status was never
        retried. Must now revert to 'unknown' on a settlement failure so a
        later recovery pass gets another chance."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        exit_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_settle_fail"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_settle_fail",
                "status": "executed",
                "fill_count_fp": "10.00",
            },
            False,
        )

        # Force a NON-race exception (sqlite3.OperationalError-shaped, not
        # the "lost a race" RuntimeError this code already handled in round
        # 1) to prove the broader except now catches it too.
        with patch(
            "execution_log.record_live_exit_fill",
            side_effect=OSError("database is locked"),
        ):
            _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        exit_row = next(o for o in orders if o["id"] == exit_row_id)
        assert exit_row["status"] == "unknown", (
            "a settlement failure must leave the row 'unknown' so the next "
            "recovery pass retries it -- marking it 'filled' anyway makes "
            "the failure permanent (the row leaves get_unknown_live_orders()"
            " forever)"
        )
        position_row = next(o for o in orders if o["id"] == position_id)
        assert position_row["settled_at"] is None

        # Now simulate the next recovery pass succeeding (DB no longer
        # locked) -- confirms the row genuinely IS retried, not just left
        # unknown forever with no path back to resolution.
        _recover_pending_orders(mock_client)
        orders = execution_log.get_recent_orders(limit=10)
        exit_row = next(o for o in orders if o["id"] == exit_row_id)
        assert exit_row["status"] == "filled"
        position_row = next(o for o in orders if o["id"] == position_id)
        assert position_row["settled_at"] is not None

    def test_concurrent_recovery_passes_settle_exit_order_only_once(self):
        """Opus review follow-up (round 2, MEDIUM): _recover_pending_orders
        runs concurrently across processes (cron.py vs cmd_watch's
        standalone call, deliberately not serialized behind the cron lock
        per AUD-0013). Simulating two passes racing on the SAME unknown
        exit row (both reading it before either resolves it) must settle
        the position's quantity/pnl exactly ONCE, not twice."""
        import execution_log

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        exit_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_race"},
        )

        # Both "processes" already hold the same unknown-row snapshot
        # (mirrors two concurrent get_unknown_live_orders() reads before
        # either has claimed the row) -- call the resolution logic twice
        # in a row without re-fetching, exercising claim_unknown_order's
        # atomicity directly rather than the outer query.
        import execution_log as _el

        rows_snapshot = _el.get_unknown_live_orders()
        assert len(rows_snapshot) == 1

        from order_executor import _settle_recovered_exit_order

        # First "process" wins the claim and settles.
        assert _el.claim_unknown_order(exit_row_id) is True
        assert _settle_recovered_exit_order(exit_row_id, rows_snapshot[0], 4) is True
        _el.log_order_result(exit_row_id, status="filled", response={}, fill_quantity=4)

        # Second "process" was holding the SAME pre-race snapshot and now
        # tries to claim the same row -- must lose, since it's no longer
        # 'unknown'.
        assert _el.claim_unknown_order(exit_row_id) is False

        orders = execution_log.get_recent_orders(limit=10)
        position_row = next(o for o in orders if o["id"] == position_id)
        # gross_pnl = 4 * (0.20 - 0.40) = -0.80, fee = 0.05, pnl = -0.85 --
        # must be recorded exactly once, not twice (-1.70), and the position
        # reduced by 4 once, not twice (fill_quantity == 6, not 2).
        assert position_row["fill_quantity"] == 6
        assert execution_log.get_today_live_loss() == pytest.approx(0.85)

    def test_missing_client_order_id_leaves_unknown_without_crashing(self):
        """A malformed 'unknown' row with no stored client_order_id must be
        skipped safely (left unknown, warning logged), not crash the whole
        recovery pass and block every other row's reconciliation."""
        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={},
        )

        _recover_pending_orders(client=None)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "unknown"

    def test_unknown_row_processed_when_zero_pending_rows_exist(self):
        """Regression guard: the pending-rows loop's early return used to
        make the whole function bail out (skipping the unknown-rows loop
        entirely) whenever there were zero pending rows -- this is the
        specific empty-pending trigger condition that exposed it."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        unknown_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_recheck4"},
        )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            None, False
        )

        # No pending rows exist at all -- get_pending_live_orders() returns [].
        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == unknown_row_id)
        assert row["status"] == "failed", (
            "unknown-row reconciliation was skipped because the pending-rows "
            "loop had nothing to do"
        )

    def test_pending_and_unknown_rows_both_processed_in_one_call(self):
        """Opus review follow-up: the previous version of this test's name
        implied a genuinely mixed pending+unknown call but only ever logged
        an unknown row (zero pending) -- a real regression guard for the
        early-return bug (test above), but not what this name claims. Now
        exercises both loops with real, distinct rows in the SAME call and
        confirms both resolve correctly."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        pending_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=3,
            price=0.50,
            status="pending",
            live=True,
            response={"order_id": "ord_pending_1"},
        )
        unknown_row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T76",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_recheck5"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_pending_1",
            "status": "executed",
            "fill_count_fp": "3.00",
        }
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {"order_id": "ord_unknown_1", "status": "resting"},
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        pending_row = next(o for o in orders if o["id"] == pending_row_id)
        unknown_row = next(o for o in orders if o["id"] == unknown_row_id)
        assert pending_row["status"] == "filled"
        assert unknown_row["status"] == "pending"


class TestRecoverSentOrders:
    """Batch-22 item 2: status='sent' -- log_order()'s transient
    pre-placement default -- was written by TWO sources with no path back to
    a real outcome afterward: (a) main.cmd_order's own pre-log crashing
    before ANY log_order_result call, and (b) the pending-loop's own "no
    order_id" fallback just above (TestRecoverPendingOrders). Every live
    pre-log call site now stashes client_order_id in response BEFORE the API
    call (kalshi_client.compute_client_order_id) -- _recover_pending_orders
    promotes a 'sent' row carrying that id to 'unknown' so the existing
    client_order_id reconciliation (TestRecoverUnknownOrders above) picks it
    up on the SAME pass, instead of it being a dead end."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_sent_row_with_client_order_id_is_promoted_and_resolved(self):
        """The core fix: a 'sent' row carrying a client_order_id (e.g. from
        main.cmd_order's pre-log, then a crash before the real outcome was
        recorded) must resolve to 'filled' in the SAME recovery pass, not
        stay stuck 'sent' forever."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
            response={"client_order_id": "coid_sent_recover"},
        )
        # Batch-22 F1/F2 follow-up: the promotion loop now requires a row
        # to be past _SENT_PROMOTION_MIN_AGE_MINUTES before touching it (an
        # in-flight placement legitimately sits at 'sent' too) -- backdate
        # to simulate a genuinely stale row a real crash would leave behind,
        # not the artificial just-now freshness this test would otherwise
        # create. See TestRecoverSentOrders' own in-flight/age-guard tests
        # further down for the guard's own direct coverage.
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = datetime('now', '-30 minutes') "
                "WHERE id = ?",
                (row_id,),
            )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_found_from_sent",
                "status": "executed",
                "fill_count_fp": "2.00",
            },
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        mock_client._find_orders_by_client_ids.assert_called_once_with(
            {"coid_sent_recover"}
        )

    def test_sent_row_without_client_order_id_stays_sent(self):
        """No recoverable id (e.g. a row from before this fix) must leave
        the row exactly as it was -- matching the prior fail-safe behavior
        (dedup keeps blocking a re-placement) rather than guessing."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
        )

        mock_client = MagicMock()
        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "sent"
        mock_client._find_orders_by_client_ids.assert_not_called()

    def test_pending_row_with_no_order_id_preserves_client_order_id_through_to_sent(
        self,
    ):
        """A 'pending' row (e.g. from _place_live_order's pre-log) that
        crashes with no order_id recorded must carry its own already-stashed
        client_order_id through the pending->sent transition -- previously
        log_order_result's unconditional response overwrite (no COALESCE)
        wiped it to NULL, permanently orphaning the row even though the id
        was captured at pre-log time."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"client_order_id": "coid_preserved"},
        )
        # Batch-22 F1/F2 follow-up: backdated so the SAME-pass sent->unknown
        # promotion below (which now requires the row be past
        # _SENT_PROMOTION_MIN_AGE_MINUTES) still fires -- a real crash-
        # recovery scenario has this same gap in practice (recovery runs on
        # a periodic cron/watch cadence, not instantaneously after the
        # original pre-log).
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = datetime('now', '-30 minutes') "
                "WHERE id = ?",
                (row_id,),
            )

        mock_client = MagicMock()
        # No order_id in the stored response -> falls into the "no order_id"
        # branch (writes 'sent', preserving response), then this same call
        # promotes it straight to 'unknown' and re-checks it -- uncertain=True
        # here so it stays 'unknown' rather than resolving further, isolating
        # exactly the claim this test is about: the id survived the
        # pending->sent transition well enough to be correctly re-checked at
        # all (a wiped response would have skipped the re-check entirely,
        # per test_sent_row_without_client_order_id_stays_sent above).
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        _recover_pending_orders(mock_client)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT status, response FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["status"] == "unknown"
        assert row["response"] is not None
        import json as _json

        assert _json.loads(row["response"])["client_order_id"] == "coid_preserved"
        mock_client._find_orders_by_client_ids.assert_called_once_with(
            {"coid_preserved"}
        )

    def test_pending_to_sent_to_unknown_resolves_within_one_recovery_call(self):
        """End-to-end: a 'pending' row with no order_id but a captured
        client_order_id gets demoted to 'sent' (preserving the id) and then
        promoted straight to 'unknown' and reconciled -- all inside ONE
        _recover_pending_orders() call, since the promotion loop runs after
        the pending loop but before the unknown loop reads its rows."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"client_order_id": "coid_full_chain"},
        )
        # Batch-22 F1/F2 follow-up: see the matching comment on
        # test_pending_row_with_no_order_id_preserves_client_order_id_through_to_sent
        # above -- backdated so the same-pass promotion still fires.
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = datetime('now', '-30 minutes') "
                "WHERE id = ?",
                (row_id,),
            )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_full_chain",
                "status": "executed",
                "fill_count_fp": "2.00",
            },
            False,
        )

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"

    def test_in_flight_sent_row_is_not_promoted(self):
        """Opus review follow-up (F1/F2/F8): a 'sent' row younger than
        order_executor._SENT_PROMOTION_MIN_AGE_MINUTES must be left alone --
        it may still be an ordinary in-flight placement (main.cmd_order's
        own pre-log status, not just a crash artifact) that the ORIGINAL
        placing process hasn't finished with yet. Promoting it here would
        race that process's own eventual log_order_result() call."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
            response={"client_order_id": "coid_in_flight"},
        )
        # placed_at defaults to "now" -- well inside the age guard's margin.

        mock_client = MagicMock()
        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "sent", (
            "an in-flight (just-now) 'sent' row must not be touched by "
            "recovery -- promoting it risks racing the process still "
            "placing it"
        )
        mock_client._find_orders_by_client_ids.assert_not_called()

    def test_old_sent_row_past_the_age_guard_is_promoted(self):
        """Positive control for the test above: once a 'sent' row is
        genuinely old (past any realistic in-flight window), it must still
        be promoted and reconciled -- the age guard delays recovery, it
        doesn't disable it."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
            response={"client_order_id": "coid_stale"},
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = datetime('now', '-30 minutes') "
                "WHERE id = ?",
                (row_id,),
            )

        mock_client = MagicMock()
        mock_client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {
                "order_id": "ord_stale_found",
                "status": "executed",
                "fill_count_fp": "2.00",
            },
            False,
        )
        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        mock_client._find_orders_by_client_ids.assert_called_once_with({"coid_stale"})

    def test_paper_sent_rows_are_never_promoted(self):
        """F8: get_sent_live_orders (and therefore the promotion loop) must
        stay scoped to live=1 -- a paper order's own 'sent' pre-log default
        must never be touched by live-order recovery machinery."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=False,
            response={"client_order_id": "coid_paper_should_be_ignored"},
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = datetime('now', '-30 minutes') "
                "WHERE id = ?",
                (row_id,),
            )

        mock_client = MagicMock()
        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "sent"
        mock_client._find_orders_by_client_ids.assert_not_called()

    def test_claim_sent_order_fails_if_row_already_resolved(self):
        """Opus review follow-up (F3): claim_sent_order must be an atomic
        claim (WHERE status='sent'), not an unconditional overwrite -- a
        row a concurrent process already resolved (e.g. to 'filled') must
        never be silently reverted back to a bare {"client_order_id": ...}
        'unknown' response, which would wipe real settlement data
        (order_id, fill_quantity) and make a filled position invisible to
        get_filled_unsettled_live_orders() again."""
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
            response={"client_order_id": "coid_race"},
        )
        # Simulate a concurrent process having already resolved this row.
        execution_log.log_order_result(
            row_id,
            status="filled",
            response={"order_id": "ord_already_resolved", "status": "executed"},
            fill_quantity=2,
        )

        won = execution_log.claim_sent_order(row_id, "coid_race")

        assert won is False
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT status, response FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["status"] == "filled", (
            "the concurrent writer's real resolution must survive untouched"
        )
        import json as _json

        assert _json.loads(row["response"])["order_id"] == "ord_already_resolved"

    def test_claim_sent_order_succeeds_when_still_sent(self):
        """Positive control for the test above."""
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="sent",
            live=True,
            response={"client_order_id": "coid_ok"},
        )

        won = execution_log.claim_sent_order(row_id, "coid_ok")

        assert won is True
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT status FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["status"] == "unknown"


class TestFinalizeCancel:
    """F9 followup: _finalize_cancel() is the shared post-cancel_order()
    fill-check used by both the pre-close cancel and GTC-age cancel paths in
    _poll_pending_orders -- covering it directly here exercises both call
    sites without duplicating the trigger machinery for each."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_zero_fill_cancel_stays_canceled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        _finalize_cancel(mock_client, "ord_1", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "canceled"

    def test_partial_fill_cancel_promotes_to_filled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "4.00",
        }

        _finalize_cancel(mock_client, "ord_2", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 4

    def test_get_order_failure_falls_back_to_plain_canceled(self):
        """The cancel itself already happened -- a failed follow-up query
        must not leave the row stuck on 'pending' or raise; it must still
        record the cancel, just without fill-count enrichment."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        _finalize_cancel(mock_client, "ord_3", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "canceled"


class TestPollPendingOrders:
    def test_filled_order_updates_status(self, monkeypatch):
        """_poll_pending_orders updates a pending live order to 'filled' when API returns filled."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        import execution_log
        import main

        # Use a fresh temp DB
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        monkeypatch.setattr(execution_log, "DB_PATH", Path(tmp.name))
        monkeypatch.setattr(execution_log, "_initialized", False)

        # Log a pending live order — response uses the real Kalshi API envelope shape
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc123"},
        )

        # Mock client that returns Kalshi's real "executed" status (not "filled" --
        # that's this bot's own internal term, translated by
        # _kalshi_status_to_internal; Kalshi's actual enum is
        # resting/canceled/executed).
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_abc123",
            "status": "executed",
            # F9: Kalshi's real field is "fill_count_fp" (fixed-point string),
            # not "fill_quantity" -- confirmed against the same shape main.py
            # already reads fill_count_fp from.
            "fill_count_fp": "2.00",
        }

        main._poll_pending_orders(mock_client)

        # Verify the order was updated
        orders = execution_log.get_recent_orders(limit=10)
        assert orders[0]["status"] == "filled"
        # F9: fill_quantity must be parsed from fill_count_fp, not left None
        # (which would silently fall back to the full requested quantity at
        # settlement instead of the true fill count).
        assert orders[0]["fill_quantity"] == pytest.approx(2.0)

        import gc

        gc.collect()
        execution_log._initialized = False
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)


class TestPollPendingOrdersExtended:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        from pathlib import Path

        Path(self._tmp.name).unlink(missing_ok=True)

    def test_gtc_cancel_fires_for_old_pending_order(self):
        """Orders older than gtc_cancel_hours are cancelled via the API."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc"},
        )
        # Backdate placed_at to 2 hours ago
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id)
            )

        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}

        config = {"gtc_cancel_hours": 1}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_called_once_with("ord_abc")
        orders = execution_log.get_recent_orders(limit=10)
        # F8: unified to "canceled" (American, matching Kalshi's own API and
        # _kalshi_status_to_internal) — was the British "cancelled" spelling,
        # which was invisible to was_ordered_recently's NOT IN ('failed',
        # 'canceled') exclusion, wrongly blocking re-entry for 7 days.
        assert orders[0]["status"] == "canceled"

    def test_gtc_age_cancel_with_partial_fill_resolves_to_filled(self):
        """F9 followup: cancel_order() alone doesn't reveal whether the order
        partially filled right before cancellation -- Kalshi has no distinct
        "partially filled" status. _finalize_cancel() must query get_order()
        after cancelling and promote to "filled" with the real fill count
        when one exists, or the position silently never reaches settlement."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_partial_gtc"},
        )
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id)
            )

        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "order_id": "ord_partial_gtc",
            "status": "canceled",
            "fill_count_fp": "3.00",
        }

        config = {"gtc_cancel_hours": 1}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_called_once_with("ord_partial_gtc")
        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 3

    def test_gtc_cancel_skips_fresh_orders(self):
        """Orders younger than gtc_cancel_hours are not cancelled."""
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_fresh"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {"status": "resting"}

        config = {"gtc_cancel_hours": 999}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_not_called()

    def test_settlement_recorded_for_finalized_market(self):
        """When a filled YES order's market is finalized (YES wins), P&L is computed and recorded."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 1
        assert order["settled_at"] is not None
        # pnl = 2 * (1 - 0.55) * (1 - fee); live fills are always maker
        # (resting midpoint GTC limit), which pays $0 on this bot's markets —
        # see utils.KALSHI_MAKER_FEE_RATE. pnl = 2 * 0.45 * 1.0 = 0.90
        assert order["pnl"] == pytest.approx(0.90, rel=1e-3)

    def test_settlement_race_loss_skips_add_live_loss(self):
        """Batch-31 M-2: record_live_settlement now reports whether it won
        the settled_at race (guarded on settled_at IS NULL) -- the caller
        here must skip add_live_loss() when it lost, or a concurrent
        writer's already-accounted pnl gets double-applied to the daily
        loss counter. Simulates the race by settling the row (via a
        protective early exit, same shape as a concurrent cron/watch writer)
        from inside record_live_settlement's own call, so the loop's
        settlement query still finds an unsettled row at query time but the
        UPDATE loses the race when it actually runs."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )

        real_record_live_settlement = execution_log.record_live_settlement

        def _settle_concurrently_then_call(*args, **kwargs):
            execution_log.record_live_early_exit(row_id, 0.60, "stop_loss", 0.05)
            return real_record_live_settlement(*args, **kwargs)

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        loss_before = execution_log.get_today_live_loss()
        with patch.object(
            execution_log,
            "record_live_settlement",
            side_effect=_settle_concurrently_then_call,
        ):
            main._poll_pending_orders(mock_client, config={})

        # The early exit's own pnl (0.05) must survive untouched -- not
        # overwritten by the natural-settlement branch's pnl.
        order = execution_log.get_order_by_id(row_id)
        assert order["pnl"] == pytest.approx(0.05)
        assert order["exit_reason"] == "stop_loss"
        # add_live_loss must NOT have been called for the lost race's pnl --
        # the daily loss counter is unchanged from before this settlement
        # attempt (the early exit's own pnl was a gain, not a loss, so it
        # never touches add_live_loss either).
        assert execution_log.get_today_live_loss() == pytest.approx(loss_before)

    def test_no_side_settlement_yes_wins(self):
        """NO bet loses when YES wins: pnl = -qty * price (NO contract cost)."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        # price stores the NO contract price: YES=0.40 market → NO costs 0.60
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=3,
            price=0.60,
            status="filled",
            live=True,
            fill_quantity=3,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",  # YES wins → NO loses
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 1
        assert order["settled_at"] is not None
        # pnl = -3 * 0.60 = -1.80
        assert order["pnl"] == pytest.approx(-1.80, rel=1e-3)

    def test_no_side_settlement_no_wins(self):
        """NO bet wins when NO wins: pnl = qty * (1 - price) * (1 - fee)."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        # price stores the NO contract price: YES=0.40 market → NO costs 0.60
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=3,
            price=0.60,
            status="filled",
            live=True,
            fill_quantity=3,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "no",  # NO wins → NO bet pays out
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 0
        assert order["settled_at"] is not None
        # pnl = 3 * (1 - 0.60) * (1 - fee); maker fee is $0 on this bot's
        # markets — see utils.KALSHI_MAKER_FEE_RATE. pnl = 3 * 0.40 * 1.0 = 1.20
        assert order["pnl"] == pytest.approx(1.20, rel=1e-3)

    def test_settlement_loss_does_not_double_count(self):
        """F7: a losing settlement must add exactly the loss to the daily
        counter, not double it. Before the fix, add_live_loss(cost) at
        placement PLUS add_live_loss(-pnl) at settlement (pnl=-cost for a
        full loss) added the same cost twice."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )
        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "no",  # YES bet loses
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        # pnl = -2 * 0.55 = -1.10 -> add_live_loss(-pnl) adds exactly 1.10.
        # 2.20 (double) would indicate the old placement-time double-count.
        assert execution_log.get_today_live_loss() == pytest.approx(1.10, rel=1e-3)

    def test_settlement_win_credits_the_counter(self):
        """F7: a winning settlement must credit (reduce) the daily counter —
        under the old bug, a win left cost-minus-profit stuck as a phantom
        'loss' because the placement-time cost was never refunded."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )
        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",  # YES bet wins
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        # pnl = 2*(1-0.55)*(1-fee) = 0.90 (profit; maker fee is $0 on this
        # bot's markets — see utils.KALSHI_MAKER_FEE_RATE) -> add_live_loss(-pnl)
        # is a credit of -0.90, not a lingering positive "loss".
        assert execution_log.get_today_live_loss() == pytest.approx(-0.90, rel=1e-3)

    def test_settlement_uses_taker_fee_for_market_order_type(self):
        """AUD-0003: an entry filled via a taker (IOC) order -- order_type=
        'market', e.g. cmd_order's live buys or the auto-trader's
        taker-cross reprice fallback -- must be settled with the real
        KALSHI_FEE_RATE at natural market expiry, not the $0
        KALSHI_MAKER_FEE_RATE every row used to get unconditionally."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main
        from utils import kalshi_taker_fee

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            order_type="market",
            status="filled",
            live=True,
            fill_quantity=2,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        # Batch-22 items 3+6: gross = 2 * (1 - 0.55) = 0.90; fee =
        # ceil(0.07*2*0.55*0.45*100)/100 = 0.04. pnl = 0.90 - 0.04 = 0.86 --
        # NOT the maker-fee 0.90 test_settlement_recorded_for_finalized_market
        # pins for the identical price/quantity with order_type='limit' (the
        # default), and NOT the old flat-KALSHI_FEE_RATE approximation.
        # Literal expected value (opus review follow-up: a call computed
        # from kalshi_taker_fee itself can't catch a bug inside that
        # function) cross-checked against utils.kalshi_taker_fee(2, 0.55) as
        # a positive control that the two independent computations agree.
        assert order["pnl"] == pytest.approx(0.86)
        assert kalshi_taker_fee(2, 0.55) == pytest.approx(0.04)

    def test_settlement_defaults_to_taker_fee_for_unrecognized_order_type(self):
        """AUD-0003: a missing/unrecognized order_type must NOT be assumed
        free (maker) -- the safe failure direction is understating P&L, not
        overstating it (the exact risk the audit flagged: an inflated P&L
        makes the daily-loss circuit breaker less likely to trip when it
        legitimately should)."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )
        # Simulate a pre-fix / legacy row with no meaningful order_type.
        with execution_log._conn() as con:
            con.execute("UPDATE orders SET order_type = NULL WHERE id = ?", (row_id,))

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        order = execution_log.get_recent_orders(limit=10)[0]
        # Literal (see the matching test above for the hand-computed
        # derivation) -- not derived from the function under test.
        assert order["pnl"] == pytest.approx(0.86)


class TestPlaceLiveOrderDedup:
    """_place_live_order must return (False, 0.0) when the ticker was already
    ordered this cycle — testing the dedup check INSIDE the function itself,
    not the higher-level _auto_place_trades wrapper that mocks it away."""

    def test_returns_false_when_already_ordered_this_cycle(self):
        import os
        from unittest.mock import MagicMock, patch

        import order_executor

        ticker = "KXHIGHNY-26MAY17-T72"
        cycle = "18z"
        mock_client = MagicMock()

        analysis = {
            "market": {"yes_bid": 60, "yes_ask": 65, "no_bid": 35},
            "kelly_quantity": 3,
            "edge": 0.12,
        }
        config = {
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "max_trade_dollars": 50,
        }

        with (
            # Pass the env / gate checks
            _live_gates_open(),
            patch.dict(
                os.environ,
                {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"},
            ),
            # Daily loss and open-position checks pass
            patch("order_executor.execution_log.get_today_live_loss", return_value=0),
            patch("order_executor._count_open_live_orders", return_value=0),
            # Dedup: ticker already ordered this cycle
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=True,
            ),
        ):
            placed, cost = order_executor._place_live_order(
                ticker=ticker,
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle=cycle,
            )

        assert placed is False, (
            "should not place when ticker already ordered this cycle"
        )
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_places_order_when_not_yet_ordered(self):
        """Positive control: order fires when dedup finds no prior order this cycle."""
        import os
        from unittest.mock import MagicMock, patch

        import order_executor

        ticker = "KXHIGHNY-26MAY17-T72"
        cycle = "18z"
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order": {"id": "ord_abc", "status": "resting"}
        }

        analysis = {
            "market": {"yes_bid": 60, "yes_ask": 65, "no_bid": 35},
            "kelly_quantity": 3,
            "edge": 0.12,
        }
        config = {
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "max_trade_dollars": 50,
        }

        with (
            _live_gates_open(),
            patch.dict(
                os.environ,
                {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"},
            ),
            patch("order_executor.execution_log.get_today_live_loss", return_value=0),
            patch("order_executor._count_open_live_orders", return_value=0),
            # Dedup: not yet ordered this cycle
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=False,
            ),
            patch("order_executor.execution_log.log_order", return_value=1),
            patch("order_executor.execution_log.log_order_result"),
        ):
            placed, cost = order_executor._place_live_order(
                ticker=ticker,
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle=cycle,
            )

        assert placed is True
        mock_client.place_order.assert_called_once()


class TestFinalizeCancelReturnValue:
    """_finalize_cancel now returns (status, fill_count, raw_api_status) so
    reprice/taker-cross logic can decide whether it's safe to place a
    replacement order -- raw_api_status specifically so callers can tell a
    genuine Kalshi-confirmed "canceled" apart from an unrecognized/in-flight
    status (e.g. "resting") that resolved_status defaults to "canceled" too."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_returns_canceled_zero_on_clean_cancel(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_1", row_id
        )
        assert status == "canceled"
        assert fill_count == 0
        assert raw_api_status == "canceled"

    def test_successful_verification_writes_response(self):
        """Independent review (batch-31 F8): the success branch used to
        omit response= from log_order_result, unconditionally nulling this
        row's response (order_id) the same way the exception branch used to
        before this batch's L-10(a) fix -- the two branches of this one
        function shouldn't disagree about preserving it."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
            "order_id": "ord_verified",
        }

        _finalize_cancel(mock_client, "ord_verified", row_id)

        row = execution_log.get_order_by_id(row_id)
        import json

        assert json.loads(row["response"]) == {
            "status": "canceled",
            "fill_count_fp": "0.00",
            "order_id": "ord_verified",
        }

    def test_returns_filled_with_count_on_partial_fill(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "4.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_2", row_id
        )
        assert status == "filled"
        assert fill_count == 4
        assert raw_api_status == "canceled"

    def test_returns_sentinel_negative_one_when_verification_query_fails(self):
        """Fill state genuinely unknown here -- callers must fail closed
        (never place a replacement) rather than assume fill_count=0."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_3", row_id
        )
        assert status == "canceled"
        assert fill_count == -1
        assert raw_api_status is None

    def test_verification_failure_preserves_prior_fill_quantity_and_response(self):
        """Batch-31 L-10(a): the exception fallback used to call
        log_order_result(row_id, status="canceled") bare -- fill_quantity
        and response are non-COALESCE columns (log_order_result's UPDATE is
        unconditional), so that nulled out whatever this row already had
        recorded: a genuine partial fill from an earlier poll, and the
        response carrying order_id/client_order_id. A partially-filled
        position could then go fully untracked. This test seeds the row
        with a real prior fill_quantity and response BEFORE the
        verification query fails, and proves both survive unchanged."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_prior", "client_order_id": "cid_prior"},
        )
        # Simulate an earlier poll having already observed a partial fill on
        # this same pending row before this cancel attempt.
        execution_log.log_order_result(
            row_id,
            status="pending",
            fill_quantity=3,
            response={"order_id": "ord_prior", "client_order_id": "cid_prior"},
        )

        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        _finalize_cancel(mock_client, "ord_prior", row_id)

        row = execution_log.get_order_by_id(row_id)
        assert row["fill_quantity"] == 3
        import json

        assert json.loads(row["response"]) == {
            "order_id": "ord_prior",
            "client_order_id": "cid_prior",
        }

    def test_malformed_stored_response_does_not_crash_the_fallback(self):
        """Independent review (batch-31 F10): the exception fallback's own
        best-effort json.loads of the prior response must not itself raise
        out of an already-handling except block on a malformed/corrupted
        response column -- unreachable in normal operation (the column is
        only ever json.dumps-written) but a crash on defensive preservation
        would be worse than just losing the field."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET response = ? WHERE id = ?",
                ("{not valid json", row_id),
            )

        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_corrupt", row_id
        )

        assert status == "canceled"
        assert fill_count == -1
        row = execution_log.get_order_by_id(row_id)
        # Batch-58 item 7: this used to assert response was None. That was
        # incidental, not intended -- the fallback's json.loads failed, so it
        # passed response=None, and log_order_result's then-unconditional
        # UPDATE nulled the column. log_order_result now COALESCEs response,
        # so a caller that passes None leaves the stored value alone. The
        # corrupt string is preserved verbatim instead of being destroyed,
        # which is the better outcome for a value an operator may need to
        # inspect. What this test actually exists to prove -- that the
        # defensive json.loads does not raise out of an already-handling
        # except block -- is the three assertions around this one.
        assert row["response"] == "{not valid json"
        assert row["status"] == "canceled"

    def test_raw_api_status_preserved_when_still_resting(self):
        """A cancel that hasn't propagated yet (Kalshi still reports
        "resting") must surface that in raw_api_status even though
        resolved_status collapses it to "canceled" for the pre-existing
        GTC/pre-close callers that don't need this distinction."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_4", row_id
        )
        assert status == "canceled"  # collapsed default, for existing callers
        assert raw_api_status == "resting"  # but the raw truth is preserved


class TestGetCurrentBook:
    def test_uses_ws_cache_when_fresh_and_complete(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        with patch(
            "kalshi_ws.get_cached_book",
            return_value={"yes_bid": 0.40, "yes_ask": 0.45, "mid_price": 0.425},
        ):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.40, "yes_ask": 0.45}
        mock_client.get_market.assert_not_called()

    def test_falls_back_to_rest_when_ws_cache_missing(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"yes_bid": 0.38, "yes_ask": 0.42}
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.38, "yes_ask": 0.42}
        mock_client.get_market.assert_called_once()

    def test_falls_back_to_rest_when_ws_entry_one_sided(self):
        """A one-sided WS book (no real ask) must not be treated as usable --
        falls through to REST. kalshi_ws.parse_message's ticker branch
        defaults a missing side to 0.0, not None
        (yes_ask_str = inner.get("yes_ask") or "0") -- this is the real
        sentinel production actually produces, not None."""
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"yes_bid": 0.38, "yes_ask": 0.42}
        with patch(
            "kalshi_ws.get_cached_book",
            return_value={"yes_bid": 0.40, "yes_ask": 0.0, "mid_price": 0.40},
        ):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.38, "yes_ask": 0.42}

    def test_returns_none_when_both_sources_unavailable(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.side_effect = ConnectionError("down")
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book is None

    def test_returns_none_when_rest_market_has_no_quote(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {}
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book is None


class TestLiveMinEdge:
    def test_defaults_to_min_edge_constant(self, monkeypatch):
        import order_executor
        from order_executor import _live_min_edge

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        assert _live_min_edge({}) == 0.07

    def test_uses_confidence_tier_when_spread_present(self):
        from unittest.mock import patch

        from order_executor import _live_min_edge

        with patch("utils.get_min_edge_for_confidence", return_value=0.20) as mock_tier:
            result = _live_min_edge({"ensemble_spread": 3.5})

        assert result == 0.20
        mock_tier.assert_called_once_with(3.5, is_live=True)

    def test_falls_back_to_min_edge_on_tier_exception(self, monkeypatch):
        import order_executor
        from order_executor import _live_min_edge

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        from unittest.mock import patch

        with patch(
            "utils.get_min_edge_for_confidence", side_effect=RuntimeError("boom")
        ):
            result = _live_min_edge({"ensemble_spread": 3.5})

        assert result == 0.07


class TestClearsTakerFee:
    """_clears_taker_fee recomputes net_edge with the real taker fee instead
    of the maker fee analyze_trade() actually used -- deciding whether
    crossing as taker (guaranteed fill, real fee) beats continuing to wait."""

    def test_true_for_strong_edge(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        # net_ev = 0.85*0.50*0.93 - 0.15*0.50 = 0.32025; /0.50 = 0.6405 >> 0.07
        assert _clears_taker_fee(analysis) is True

    def test_false_for_thin_edge(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        # net_ev = 0.53*0.50*0.93 - 0.47*0.50 = 0.01145; /0.50 = 0.0229 < 0.07
        assert _clears_taker_fee(analysis) is False

    def test_no_side_computed_correctly(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.15,  # P(NO wins) = 0.85
            "entry_price": 0.50,
            "recommended_side": "no",
        }
        assert _clears_taker_fee(analysis) is True

    def test_missing_entry_price_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee({"forecast_prob": 0.8, "recommended_side": "yes"})
            is False
        )

    def test_missing_forecast_prob_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee({"entry_price": 0.5, "recommended_side": "yes"}) is False
        )

    def test_invalid_side_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee(
                {
                    "forecast_prob": 0.8,
                    "entry_price": 0.5,
                    "recommended_side": "maybe",
                }
            )
            is False
        )


class TestCancelAndVerifySafeToReplace:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _seed_row(self):
        import execution_log

        return execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )

    def test_true_when_confirmed_unfilled(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_1", row_id) is True
        mock_client.cancel_order.assert_called_once_with("ord_1")

    def test_false_when_partial_fill_detected(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "3.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_2", row_id) is False

    def test_false_when_cancel_call_itself_raises(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.cancel_order.side_effect = ConnectionError("down")

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_3", row_id) is False

    def test_false_when_post_cancel_verification_query_fails(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_4", row_id) is False

    def test_false_when_order_still_resting_despite_zero_fill_count(self):
        """A cancel that hasn't propagated yet (Kalshi still reports
        "resting", zero fills so far) must NOT be treated as safe to
        replace -- a taker-cross replacement placed while the original is
        still genuinely resting would silently no-op against Kalshi's
        self_trade_prevention_type="taker_at_cross" rather than fill.
        fill_count==0 alone isn't proof the order is actually gone."""
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_5", row_id) is False


class TestReplaceLiveOrder:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_gate_blocked_returns_false_and_places_nothing(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _replace_live_order

        mock_client = MagicMock()
        with patch(
            "trading_gates.pre_live_trade_check",
            side_effect=RuntimeError("TRADING_PAUSED"),
        ):
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is False
        mock_client.place_order.assert_not_called()

    def test_success_logs_replaces_order_id(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_new"}
        with _live_gates_open():
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is True
        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["price"] == pytest.approx(0.52))
        assert new_row["replaces_order_id"] == 99
        assert new_row["status"] == "pending"
        assert new_row["order_type"] == "limit"

    def test_place_order_failure_logs_failed_status(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.side_effect = ConnectionError("down")
        with _live_gates_open():
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is False
        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["replaces_order_id"] == 99)
        assert new_row["status"] == "failed"

    def test_taker_cross_logged_as_market_order_type(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_taker"}
        with _live_gates_open():
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.60,
                "immediate_or_cancel",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["replaces_order_id"] == 99)
        assert new_row["order_type"] == "market"

    def test_replacement_cycle_key_scoped_to_replaces_order_id(self):
        """AUD batch-23 #1: the idempotency-key string passed to
        client.place_order must be scoped to this specific
        replaces_order_id, not the bare forecast cycle -- otherwise a
        taker-cross replacement landing at the same rounded price as the
        original GTC entry order would silently dedupe against it (same
        client_order_id) and never actually re-enter the position, while
        logging success."""
        from unittest.mock import MagicMock

        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_new"}
        with _live_gates_open():
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "immediate_or_cancel",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        cycle_arg = mock_client.place_order.call_args.kwargs["cycle"]
        assert cycle_arg == "2026-05-15_12z:replace:99"

    def test_two_replacements_of_different_orders_get_different_cycle_keys(self):
        """A same-priced taker-cross of TWO DIFFERENT original orders (same
        ticker/side/quantity/price, different replaces_order_id) must not
        collide with each other either -- each original order gets its own
        replacement key."""
        from unittest.mock import MagicMock

        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_new"}
        with _live_gates_open():
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "immediate_or_cancel",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )
            first_cycle = mock_client.place_order.call_args.kwargs["cycle"]
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "immediate_or_cancel",
                mock_client,
                "2026-05-15_12z",
                100,
                None,
            )
            second_cycle = mock_client.place_order.call_args.kwargs["cycle"]

        assert first_cycle != second_cycle

    def test_prelogged_client_order_id_matches_wire_cid(self):
        """Batch-31 CR-1: the pre-logged client_order_id must be
        byte-identical to the one place_order() actually sends. Previously
        the pre-log computation used the BARE cycle while place_order()
        itself derived its key from the replace-scoped cycle
        (f"{cycle}:replace:{replaces_order_id}") -- a crash in the window
        between the pre-log write and log_order_result recording the real
        outcome (the live-order watchdog's os._exit(1) can land exactly
        there) then made crash recovery re-check the WRONG id, get a
        confirmed negative, and mark a REAL live BUY 'failed', leaving an
        untracked live position with no protective exits.

        Spies on log_order's own response= kwarg at pre-log time (not the
        final row state, which place_order's mocked return value would
        overwrite) and independently re-derives the expected id from the
        cycle/time_in_force place_order() actually received, rather than
        trusting _replace_live_order's own internal computation for both
        sides of the comparison."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from kalshi_client import compute_client_order_id
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_cid_check"}

        real_log_order = execution_log.log_order
        prelog_calls = []

        def _spy_log_order(*args, **kwargs):
            prelog_calls.append(kwargs)
            return real_log_order(*args, **kwargs)

        with (
            patch.object(execution_log, "log_order", side_effect=_spy_log_order),
            _live_gates_open(),
        ):
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        posted_cycle = mock_client.place_order.call_args.kwargs["cycle"]
        posted_tif = mock_client.place_order.call_args.kwargs["time_in_force"]
        expected_cid = compute_client_order_id(
            "KXHIGH-25MAY15-T75", "yes", "buy", 5, 0.52, posted_tif, posted_cycle
        )

        assert len(prelog_calls) == 1
        assert prelog_calls[0]["response"]["client_order_id"] == expected_cid


class TestFillInstrumentation:
    """_poll_pending_orders must capture filled_at/market_mid_at_fill the
    moment a fill is first detected, for fill-latency/adverse-selection
    analysis (backlog: 'log fill latency and post-fill price drift per
    order')."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_fill_captures_latency_and_mid_price(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_fill"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "executed",
            "fill_count_fp": "2.00",
        }

        with patch(
            "order_executor._get_current_book",
            return_value={"yes_bid": 0.58, "yes_ask": 0.62},
        ):
            main._poll_pending_orders(mock_client, config={})

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "filled"
        assert row["filled_at"] is not None
        assert row["market_mid_at_fill"] == pytest.approx(0.60)

    def test_non_fill_status_leaves_instrumentation_null(self):
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_resting"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {"status": "resting"}

        main._poll_pending_orders(mock_client, config={})

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "pending"
        assert row["filled_at"] is None
        assert row["market_mid_at_fill"] is None

    def test_log_order_result_coalesce_never_nulls_out_prior_fill_data(self):
        """A later log_order_result() call on an already-instrumented row
        (e.g. from an unrelated code path) must not wipe filled_at/
        market_mid_at_fill back to NULL."""
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=2,
            filled_at="2026-05-15T12:00:00+00:00",
            market_mid_at_fill=0.60,
        )

        # Unrelated later update -- omits the instrumentation fields.
        execution_log.log_order_result(row_id, status="filled", fill_quantity=2)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["filled_at"] == "2026-05-15T12:00:00+00:00"
        assert row["market_mid_at_fill"] == pytest.approx(0.60)


class TestResolveAmendStatus:
    """order_executor._resolve_amend_status -- translates an amend_order()
    response into this bot's internal status vocabulary."""

    def test_no_remaining_count_means_pure_price_change_pending(self):
        """remaining_count/fill_count absent (both None) -- Kalshi's docs say
        these are 'only present if a fill or size change occurred', so their
        absence means a pure price reprice with no immediate cross."""
        from order_executor import _resolve_amend_status

        status, fill_count = _resolve_amend_status(
            {"order_id": "ord_1", "remaining_count": None, "fill_count": None}
        )
        assert status == "pending"
        assert fill_count is None

    def test_remaining_count_zero_means_filled(self):
        from order_executor import _resolve_amend_status

        status, fill_count = _resolve_amend_status(
            {"remaining_count": "0.00", "fill_count": "5.00"}
        )
        assert status == "filled"
        assert fill_count == 5

    def test_remaining_count_positive_means_still_pending(self):
        """Amend caused a partial fill (2 of 5) but 3 are still resting --
        must stay 'pending', not 'filled'."""
        from order_executor import _resolve_amend_status

        status, fill_count = _resolve_amend_status(
            {"remaining_count": "3.00", "fill_count": "2.00"}
        )
        assert status == "pending"
        assert fill_count == 2

    def test_unparseable_remaining_count_fails_to_pending(self):
        """Fail toward the safer assumption (still resting, will be
        re-verified by the next cycle's poll) rather than crashing or
        guessing 'filled' on a malformed response."""
        from order_executor import _resolve_amend_status

        status, fill_count = _resolve_amend_status(
            {"remaining_count": "not-a-number", "fill_count": None}
        )
        assert status == "pending"


class TestGetTodayLiveSpendExcludesAmended:
    """AMEND ORDER (V2): get_today_live_spend() must exclude 'amended' rows
    the same way it excludes 'canceled' -- otherwise a repriced order's
    capital is counted twice (once under its old row, once under the new
    row the amend chain logged), inflating the MAX_DAILY_SPEND check."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_amended_row_excluded_new_row_counted_once(self):
        import execution_log

        old_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.50,
            status="pending",
            live=True,
        )
        execution_log.log_order_result(old_id, status="amended")
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.55,
            status="pending",
            live=True,
            replaces_order_id=old_id,
        )

        # If 'amended' weren't excluded: 10*0.50 + 10*0.55 = $10.50 (double-counted).
        # Correct: only the live new row, 10*0.55 = $5.50.
        assert execution_log.get_today_live_spend() == pytest.approx(5.50)

    def test_mutation_amended_included_would_double_count(self):
        """Direct proof the exclusion is load-bearing: temporarily querying
        with 'amended' NOT excluded reproduces the double-counted total,
        confirming the fix addresses a real (not hypothetical) miscount."""
        from datetime import UTC, datetime

        import execution_log

        old_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.50,
            status="pending",
            live=True,
        )
        execution_log.log_order_result(old_id, status="amended")
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.55,
            status="pending",
            live=True,
            replaces_order_id=old_id,
        )

        execution_log.init_log()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT COALESCE(SUM(quantity * price), 0.0) AS total FROM orders "
                "WHERE live = 1 AND status NOT IN ('failed', 'canceled', 'cancelled') "
                "AND placed_at >= ?",
                (today,),
            ).fetchone()
        naive_total = float(row["total"])

        assert naive_total == pytest.approx(10.50)  # the bug this fix prevents
        assert execution_log.get_today_live_spend() == pytest.approx(5.50)  # the fix


class TestGetTodayLiveSpendExcludesExitOrders:
    """A protective exit (SELL) order reduces existing exposure, it isn't
    new capital deployed -- _exit_live_position() already skips the daily-
    spend GATE for exactly this reason. get_today_live_spend() must exclude
    the exit order's own logged row too, or every stop-loss/breakeven/
    model-exit fill inflates the counter that blocks NEW entries, with a
    partial-fill retry compounding it once per cycle."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_exit_order_row_excluded_entry_row_counted(self):
        import execution_log

        entry_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="filled",
            live=True,
            closes_position_id=entry_id,
        )

        # If the exit row weren't excluded: 10*0.40 + 10*0.20 = $6.00.
        # Correct: only the entry, 10*0.40 = $4.00.
        assert execution_log.get_today_live_spend() == pytest.approx(4.00)

    def test_repeated_partial_exit_retries_do_not_compound_spend(self):
        """A position whose IOC exit partial-fills every cycle logs a fresh
        exit-order row each retry -- none of them should ever count as
        spend, no matter how many cycles it takes to fully close."""
        import execution_log

        entry_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        for _ in range(3):
            execution_log.log_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                quantity=10,
                price=0.20,
                order_type="market",
                status="filled",
                live=True,
                closes_position_id=entry_id,
            )

        assert execution_log.get_today_live_spend() == pytest.approx(4.00)


class TestRepriceOrCancelPendingOrders:
    """The core reprice-or-cancel policy: cancel on edge decay, cancel+
    replace as taker when edge clears the real taker fee, cancel+replace as
    an improved maker price when the market has moved, else leave resting."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _seed_pending(self, ticker="KXHIGH-25MAY15-T75", price=0.50, age_minutes=10):
        from datetime import UTC, datetime, timedelta

        import execution_log

        row_id = execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=5,
            price=price,
            status="pending",
            live=True,
            response={"order_id": "ord_orig"},
        )
        placed_at = (datetime.now(UTC) - timedelta(minutes=age_minutes)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (placed_at, row_id)
            )
        return row_id

    def test_ticker_not_in_scan_leaves_order_untouched(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _reprice_or_cancel_pending_orders

        self._seed_pending()
        mock_client = MagicMock()

        _reprice_or_cancel_pending_orders(
            mock_client, config={}, liquid_opps=[({"ticker": "OTHER"}, {})]
        )

        mock_client.cancel_order.assert_not_called()
        rows = execution_log.get_recent_orders(limit=10)
        assert rows[0]["status"] == "pending"

    def test_empty_liquid_opps_is_a_noop(self):
        from unittest.mock import MagicMock

        from order_executor import _reprice_or_cancel_pending_orders

        self._seed_pending()
        mock_client = MagicMock()

        _reprice_or_cancel_pending_orders(mock_client, config={}, liquid_opps=[])

        mock_client.cancel_order.assert_not_called()

    def test_validation_failure_cancels_without_replacing(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        with patch(
            "order_executor._validate_trade_opportunity",
            return_value=(False, "edge decayed"),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_not_called()
        rows = execution_log.get_recent_orders(limit=10)
        assert rows[0]["status"] == "canceled"

    def test_strong_edge_and_rested_crosses_as_taker(self):
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        # net_ev_taker = 0.85*0.50*0.93 - 0.15*0.50 = 0.32025; /0.50 = 0.64 >> MIN_EDGE
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_taker"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.48, "yes_ask": 0.52},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert kwargs["time_in_force"] == "immediate_or_cancel"
        assert kwargs["price"] == pytest.approx(0.52)  # crosses at current yes_ask

    def test_order_younger_than_blanket_gate_is_untouched(self):
        """Younger than _MIN_REST_MINUTES_BEFORE_REPRICE (2 min) -> left
        resting regardless of edge strength or price movement -- blocked by
        the blanket gate before either branch is even considered (not by
        the taker-specific 4-min gate; see
        test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses
        for that narrower [2,4) window)."""
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=1)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_new"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            # Fresh midpoint (0.55) differs from the resting price (0.50) --
            # would trigger a reprice if the blanket age gate weren't
            # blocking it first.
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()

    def test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses(self):
        """The [_MIN_REST_MINUTES_BEFORE_REPRICE, _MIN_REST_MINUTES_BEFORE_TAKER_CROSS)
        window: old enough to reprice-improve (cleared the 2-min blanket
        gate) but not old enough to taker-cross (hasn't cleared the
        stricter 4-min gate) -- even with a strong edge that would
        otherwise clear the taker fee, this must amend to a new maker
        price, not cross as taker.

        AMEND ORDER (V2): the reprice-improve branch now amends the resting
        order in place (same order_id, new price) instead of cancel+
        verify+place_order -- see order_executor._amend_live_order.
        """
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=3)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        # Strong edge -- would clear the taker fee if the order were old
        # enough (see test_strong_edge_and_rested_crosses_as_taker).
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()  # amend, not cancel+replace
        mock_client.place_order.assert_not_called()
        mock_client.amend_order.assert_called_once()
        _, kwargs = mock_client.amend_order.call_args
        assert kwargs["order_id"] == "ord_orig"
        assert kwargs["price"] == pytest.approx(0.55)  # fresh midpoint
        assert kwargs["count"] == 5  # unchanged quantity

    def test_price_moved_reprices_as_new_maker_order(self):
        """AMEND ORDER (V2): reprice-improve amends in place -- see
        order_executor._amend_live_order."""
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        # Thin edge -- must NOT clear the taker fee, so this exercises the
        # reprice-improve branch, not the taker-cross branch.
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()
        mock_client.amend_order.assert_called_once()
        _, kwargs = mock_client.amend_order.call_args
        assert kwargs["price"] == pytest.approx(0.55)  # fresh midpoint

    def test_amend_success_logs_new_row_and_marks_old_row_amended(self):
        """execution_log bookkeeping for a successful amend: a NEW row is
        logged (chained via replaces_order_id, same convention as cancel+
        replace), and the OLD row's status becomes 'amended' -- distinct
        from 'canceled', since the original order was never actually
        canceled, just repriced in place."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        old_row_id = self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        rows = {r["id"]: r for r in execution_log.get_recent_orders(limit=10)}
        assert rows[old_row_id]["status"] == "amended"
        new_rows = [r for r in rows.values() if r["id"] != old_row_id]
        assert len(new_rows) == 1
        assert new_rows[0]["status"] == "pending"
        assert new_rows[0]["price"] == pytest.approx(0.55)
        assert new_rows[0]["replaces_order_id"] == old_row_id

    def test_amend_failure_leaves_old_row_pending_not_amended(self):
        """If amend_order() raises, the old row must NOT be marked
        'amended' -- the original order genuinely is still resting
        unchanged at its old price, so a future cycle must be able to
        retry it (a stale 'amended' status would make _reprice_or_cancel_
        pending_orders' status='pending' filter skip it forever)."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        old_row_id = self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.amend_order.side_effect = RuntimeError("amend rejected")

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        rows = {r["id"]: r for r in execution_log.get_recent_orders(limit=10)}
        assert rows[old_row_id]["status"] == "pending"  # untouched, not "amended"

    def test_amend_exchange_success_survives_bookkeeping_failure(self):
        """If the exchange call succeeds but a SUBSEQUENT execution_log
        write raises (e.g. a DB lock), _amend_live_order must still return
        True -- the order genuinely repriced live on the exchange, and
        misclassifying it as failed would orphan a real live order (never
        picked up again by _poll_pending_orders' status='pending' filter).
        Second-opinion-review-caught regression test: an earlier version
        wrapped the bookkeeping writes in the SAME try/except as the
        amend_order() call itself, which this test would have failed."""
        from unittest.mock import MagicMock, patch

        from order_executor import _amend_live_order

        ticker = "KXHIGH-25MAY15-T75"
        old_row_id = self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with (
            _live_gates_open(),
            patch(
                "execution_log.log_order_result",
                side_effect=RuntimeError("database is locked"),
            ),
        ):
            result = _amend_live_order(
                "ord_orig",
                ticker,
                "yes",
                5,
                0.55,
                mock_client,
                "12z",
                old_row_id,
                None,
                None,
            )

        assert result is True, (
            "amend succeeded on the exchange -- must return True even if "
            "bookkeeping afterward fails, not misreport it as a failed amend"
        )
        mock_client.amend_order.assert_called_once()

    def test_amend_cycle_key_scoped_to_this_attempts_log_id(self):
        """AUD batch-23 #1: amend_order's own key already folds in order_id
        (constant for the life of this resting order), so an oscillating
        target price (A -> B -> back to A within one forecast cycle) needs
        the caller's cycle string to carry a per-attempt discriminator too
        -- otherwise the second amend back to price A regenerates an
        identical key to the first A-priced amend and Kalshi treats it as a
        resubmit, silently no-op'ing the second reprice."""
        from unittest.mock import MagicMock

        from order_executor import _amend_live_order

        ticker = "KXHIGH-25MAY15-T75"
        old_row_id = self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with _live_gates_open():
            _amend_live_order(
                "ord_orig",
                ticker,
                "yes",
                5,
                0.55,
                mock_client,
                "12z",
                old_row_id,
                None,
                None,
            )

        cycle_arg = mock_client.amend_order.call_args.kwargs["cycle"]
        assert cycle_arg != "12z"
        assert cycle_arg.startswith("12z:amend:")

    def test_two_amends_at_the_same_price_get_different_cycle_keys(self):
        """The oscillation case itself: two separate amend attempts to the
        SAME order at the SAME target price (a price that moved away and
        back within one cycle) must still get distinct keys -- proving a
        real retry actually reaches the exchange as a fresh attempt rather
        than deduping against the earlier one."""
        from unittest.mock import MagicMock

        from order_executor import _amend_live_order

        ticker = "KXHIGH-25MAY15-T75"
        old_row_id = self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        mock_client = MagicMock()
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": None,
            "fill_count": None,
            "ts_ms": 123,
        }

        with _live_gates_open():
            _amend_live_order(
                "ord_orig",
                ticker,
                "yes",
                5,
                0.55,
                mock_client,
                "12z",
                old_row_id,
                None,
                None,
            )
            first_cycle = mock_client.amend_order.call_args.kwargs["cycle"]
            _amend_live_order(
                "ord_orig",
                ticker,
                "yes",
                5,
                0.55,
                mock_client,
                "12z",
                old_row_id,
                None,
                None,
            )
            second_cycle = mock_client.amend_order.call_args.kwargs["cycle"]

        assert first_cycle != second_cycle

    def test_price_unchanged_leaves_order_resting(self):
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                # Midpoint (0.48+0.52)/2 = 0.50, identical to the resting price.
                return_value={"yes_bid": 0.48, "yes_ask": 0.52},
            ),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()

    def test_amend_that_crosses_the_book_is_logged_as_filled(self):
        """AMEND ORDER (V2) superseded the old cancel+verify-then-replace
        fill-race protection for this branch: amend is a single atomic
        exchange-side operation, so there is no client-side window where a
        fill could race a separate cancel call (see order_executor.
        _amend_live_order's docstring). If the amend's own price change
        immediately crosses the book, Kalshi reports that in the SAME
        response (remaining_count<=0) -- _resolve_amend_status must read
        that and log the new row as 'filled', not 'pending'."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        # The new (higher) price immediately crosses the book -- all 5
        # contracts filled as a direct result of the amend itself.
        mock_client.amend_order.return_value = {
            "order_id": "ord_orig",
            "remaining_count": "0.00",
            "fill_count": "5.00",
            "ts_ms": 123,
        }

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            _live_gates_open(),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()
        mock_client.amend_order.assert_called_once()
        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["status"] == "filled")
        assert new_row["fill_quantity"] == 5
        assert rows[0]["fill_quantity"] == 5


class _LiveDBTestBase:
    """Shared execution_log DB isolation for the live-position-protection
    test classes below, matching the pattern used by every other class in
    this file."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)


class TestGetLiveOpenPositions(_LiveDBTestBase):
    def test_builds_check_function_compatible_dicts(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
            close_time="2026-05-16T12:00:00+00:00",
            entry_prob=0.62,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)

        positions = _get_live_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["ticker"] == "KXHIGH-25MAY15-T75"
        assert pos["side"] == "yes"
        assert pos["entry_price"] == pytest.approx(0.40)
        assert pos["quantity"] == 10
        assert pos["cost"] == pytest.approx(4.0)
        assert pos["entry_prob"] == pytest.approx(0.62)
        assert pos["settled"] is False

    def test_excludes_already_early_exited_positions(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.20, "stop_loss", -2.14)
        assert _get_live_open_positions() == []

    def test_prefers_filled_at_over_placed_at_for_entered_at(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=10,
            filled_at="2026-05-15T18:00:00+00:00",
        )
        positions = _get_live_open_positions()
        assert positions[0]["entered_at"] == "2026-05-15T18:00:00+00:00"

    def test_reflects_reduced_quantity_after_partial_exit(self):
        """End-to-end proof the partial-fill fix actually closes the gap:
        after _exit_live_position partially fills, the NEXT call to
        _get_live_open_positions() must see the reduced quantity, not the
        original -- otherwise a second protective-exit attempt would try to
        sell more contracts than are actually still held."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position, _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        position = _get_live_open_positions()[0]
        assert position["quantity"] == 10
        with _live_gates_open():
            _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        positions_after = _get_live_open_positions()
        assert len(positions_after) == 1
        assert positions_after[0]["quantity"] == 6
        assert positions_after[0]["cost"] == pytest.approx(0.40 * 6)


class TestUpdateLivePeakProfits(_LiveDBTestBase):
    """order_executor._update_live_peak_profits was superseded by the shared
    positions.update_peak_profits() + LivePositionStore.save_peak() combo
    (see backlog.txt's "PAPER AND LIVE POSITIONS ARE TWO LEDGERS WITH
    ADAPTER GLUE" entry) -- these exercise that combo directly, same
    fixtures/assertions as before."""

    def test_records_new_peak_when_higher(self):
        import execution_log
        from order_executor import LivePositionStore
        from positions import Position, update_peak_profits

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = Position(
            id=row_id,
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            entry_price=0.40,
            quantity=10,
            cost=4.0,
            entry_prob=None,
            close_time=None,
            entered_at=None,
            peak_profit_pct=None,
        )
        current_prices = {"KXHIGH-25MAY15-T75": {"bid": 0.55, "ask": 0.60}}
        store = LivePositionStore(client=None, cycle="test")
        update_peak_profits([position], current_prices, store.save_peak)

        # unrealized_profit_pct = (0.55 - 0.40) * 10 / 4.0 = 0.375
        assert position.peak_profit_pct == pytest.approx(0.375)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] == pytest.approx(0.375)

    def test_does_not_overwrite_a_higher_stored_peak(self):
        import execution_log
        from order_executor import LivePositionStore
        from positions import Position, update_peak_profits

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = Position(
            id=row_id,
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            entry_price=0.40,
            quantity=10,
            cost=4.0,
            entry_prob=None,
            close_time=None,
            entered_at=None,
            peak_profit_pct=0.50,  # already higher than the current tick
        )
        current_prices = {"KXHIGH-25MAY15-T75": {"bid": 0.45, "ask": 0.50}}
        store = LivePositionStore(client=None, cycle="test")
        update_peak_profits([position], current_prices, store.save_peak)

        assert position.peak_profit_pct == 0.50
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        # Never written -- stayed NULL in the DB, not overwritten with a lower value.
        assert row["peak_profit_pct"] is None


class TestExitLivePosition(_LiveDBTestBase):
    def _position(self, **overrides):
        base = {
            "id": 1,
            "ticker": "KXHIGH-25MAY15-T75",
            "side": "yes",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "close_time": "2026-05-16T12:00:00+00:00",
        }
        base.update(overrides)
        return base

    def _position_with_row(self, **overrides):
        """A position dict backed by a REAL execution_log row.

        _position()'s default id=1 does not exist in the per-test temp DB, so
        _exit_live_position's claim_position_for_exit() finds nothing to claim
        and bails before ever reaching place_order. Tests that assert an exit
        actually PLACES need a real row; tests that only assert it does not
        can use the bare _position().
        """
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        return self._position(id=row_id, **overrides)

    def test_full_exit_race_loss_does_not_crash_the_caller(self):
        """Opus review (2026-08-17), NEW-H2: execution_log.record_live_exit_fill
        raises RuntimeError when it loses a settled_at/quantity race to a
        concurrent writer -- main.cmd_order's manual sell (which does NOT go
        through claim_position_for_exit -- only the automated scanners do,
        batch-31 M-4) can still race this automated exit scanner against the
        SAME position, landing in the window after this attempt's own claim
        succeeds but before its own bookkeeping call. Left uncaught, that
        RuntimeError would climb out of _exit_live_position, through
        LivePositionStore.exit(), into _check_live_position_exits' caller in
        the watch/cron loop, which has no generic exception handler --
        crashing the ENTIRE process and leaving every OTHER live position
        unprotected from a race on just ONE. Must be caught here and treated
        as "lost the race, skip" (same as an unfilled/illiquid IOC), not
        propagate.

        Batch-31 M-4: the concurrent settlement is now injected via a
        record_live_exit_fill side effect (fires AFTER this attempt's own
        claim_position_for_exit call already succeeded), not by pre-settling
        the row before calling _exit_live_position at all -- pre-settling
        would now be caught by the claim itself (a real improvement: no live
        sell is even attempted against an already-closed position), which is
        a different scenario from this test's actual target: a race landing
        during this attempt's own execution."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        real_record_live_exit_fill = execution_log.record_live_exit_fill

        def _settle_concurrently_then_call(*args, **kwargs):
            # Simulate a concurrent writer (e.g. a manual cmd_order sell)
            # closing this exact position in the instant between this
            # attempt's own successful claim and its own bookkeeping call.
            execution_log.record_live_early_exit(row_id, 0.55, "manual_close", 1.395)
            return real_record_live_exit_fill(*args, **kwargs)

        position = self._position(id=row_id)
        with (
            _live_gates_open(),
            patch.object(
                execution_log,
                "record_live_exit_fill",
                side_effect=_settle_concurrently_then_call,
            ),
        ):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        # Must not raise. True here means "the exchange fill itself
        # succeeded" (it did), not "this attempt's own bookkeeping won" --
        # AUD-0079: this stop_loss path's own caller (_check_live_position_
        # exits) discards the return value, but elsewhere in the codebase
        # _check_live_model_exits DOES branch on it (logs "closed" and
        # increments a counter on True), so a race-loss on THAT path can
        # make its log line cite this attempt's exit_price/reason instead of
        # the concurrent writer's -- cosmetic only there too, since the DB
        # row below is unaffected and belongs to whoever actually won.
        assert result is True
        mock_client.place_order.assert_called_once()
        # The concurrent writer's real settlement must survive untouched.
        row = execution_log.get_order_by_id(row_id)
        assert row["exit_price"] == pytest.approx(0.55)
        assert row["pnl"] == pytest.approx(1.395)
        assert row["exit_reason"] == "manual_close"

    def test_partial_exit_race_loss_does_not_crash_the_caller(self):
        """Mirrors the full-exit race test above for the partial-fill
        branch -- see that test's batch-31 M-4 note on why the concurrent
        settlement is injected mid-call rather than before it."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        real_record_live_exit_fill = execution_log.record_live_exit_fill

        def _settle_concurrently_then_call(*args, **kwargs):
            execution_log.record_live_early_exit(row_id, 0.55, "manual_close", 1.395)
            return real_record_live_exit_fill(*args, **kwargs)

        position = self._position(id=row_id)
        with (
            _live_gates_open(),
            patch.object(
                execution_log,
                "record_live_exit_fill",
                side_effect=_settle_concurrently_then_call,
            ),
        ):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_called_once()
        row = execution_log.get_order_by_id(row_id)
        # The concurrent writer's settlement (and this row's fill_quantity,
        # never explicitly set here so it's still NULL) must survive
        # untouched -- not decremented by the losing writer.
        assert row["fill_quantity"] is None

    def test_partial_exit_quantity_race_loss_releases_claim_for_retry(self):
        """Independent review (batch-31 F2/F3): record_live_partial_exit's
        guard raises RuntimeError for a SECOND, distinct reason besides
        settled_at being set -- a concurrent writer shrinking the tracked
        size below what THIS attempt's own fill_count needs to subtract
        (COALESCE(fill_quantity, quantity) < filled_count). settled_at
        stays NULL in that case: the position is genuinely still open, just
        smaller than this attempt's stale snapshot expected. The prior test
        above only exercised the settled_at-set cause (via
        record_live_early_exit), which independent review proved does NOT
        kill a mutation removing this branch's release_exit_claim call --
        settled_at alone already blocks re-claiming in that case, so the
        release is a no-op there and the mutation survives undetected. This
        test reproduces the OTHER cause, where the release is actually
        load-bearing: it must both not crash AND leave the position
        re-claimable for an immediate retry against its real, now-smaller
        size."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        real_record_live_exit_fill = execution_log.record_live_exit_fill

        def _shrink_below_delta_then_call(*args, **kwargs):
            # Concurrent writer sells 8 of the 10 first, leaving only 2
            # tracked -- less than the 4 this attempt is about to subtract.
            # settled_at is untouched by record_live_partial_exit.
            execution_log.record_live_partial_exit(row_id, 8)
            return real_record_live_exit_fill(*args, **kwargs)

        position = self._position(id=row_id)
        with (
            _live_gates_open(),
            patch.object(
                execution_log,
                "record_live_exit_fill",
                side_effect=_shrink_below_delta_then_call,
            ),
        ):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_called_once()
        row = execution_log.get_order_by_id(row_id)
        assert row["settled_at"] is None
        assert row["fill_quantity"] == 2
        # The load-bearing assertion: claim released despite the RuntimeError,
        # so the next scan can immediately retry against the real remaining
        # size instead of waiting out the full TTL.
        assert execution_log.claim_position_for_exit(row_id) is not None

    def test_gate_blocked_returns_false_and_places_nothing(self):
        """Batch-58 item 4: the exit path now consults pre_live_exit_check,
        not pre_live_trade_check. Patching the REDUCED gate (and leaving the
        full one alone) is what keeps this test proving the exit is gated.
        The positive control below is what distinguishes "blocked by the
        gate under test" from "blocked by accident": with the same gate
        patched open, the identical call DOES reach place_order."""
        from unittest.mock import MagicMock, patch

        from order_executor import _exit_live_position

        mock_client = MagicMock()
        with patch(
            "trading_gates.pre_live_exit_check",
            side_effect=RuntimeError("TRADING_PAUSED"),
        ):
            result = _exit_live_position(
                mock_client, self._position(), 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_not_called()

        # Positive control for the assert_not_called() above.
        allowed_client = MagicMock()
        allowed_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with _live_gates_open():
            _exit_live_position(
                allowed_client,
                self._position_with_row(),
                0.20,
                "stop_loss",
                "2026-05-15_12z",
            )
        allowed_client.place_order.assert_called()

    def test_daily_loss_halt_does_not_block_a_protective_exit(self):
        """Batch-58 item 4 (backlog L24423), the behavioural heart of the
        change: with the daily-loss halt ACTIVE, a protective exit must
        still be placed. Before this, _exit_live_position ran the FULL gate,
        so a tripped daily-loss halt silently disabled every protective exit
        -- the bot stopped being able to close losing positions at exactly
        the moment it most needed to.

        Patches the real paper-side halt predicates rather than the gate
        itself, so this exercises the actual gate wiring end to end. The
        pre_live_trade_check assertion is the mutation-proof half: it proves
        the halt genuinely IS blocking on the full gate, so the exit getting
        through is the reduced gate's doing and not a mis-set fixture."""
        from unittest.mock import MagicMock, patch

        import trading_gates
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        mock_client.base_url = "https://api.elections.kalshi.com/trade-api/v2"

        with (
            patch.dict("os.environ", {"LIVE_TRADING_ENABLED": "true"}, clear=False),
            patch("trading_gates.is_trading_paused", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=True),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.graduation_check", return_value={"ok": True}),
        ):
            # Positive control: the FULL gate really is blocked right now.
            with pytest.raises(RuntimeError, match="Daily loss limit reached"):
                trading_gates.pre_live_trade_check(mock_client)

            # The reduced gate lets the risk-reducing order through...
            trading_gates.pre_live_exit_check(mock_client)
            # ...and so the exit actually places.
            result = _exit_live_position(
                mock_client,
                self._position_with_row(),
                0.20,
                "stop_loss",
                "2026-05-15_12z",
            )

        assert result is True
        mock_client.place_order.assert_called()

    def test_kill_switch_still_blocks_a_protective_exit(self):
        """The other half of item 4: the reduced gate is reduced, not
        absent. TRADING_PAUSED and the kill switch are the operator's
        explicit "touch nothing" instruction and stay absolute -- backlog
        L30045 (batch 63) owns giving the operator a deliberate way to close
        a position while they are engaged."""
        from unittest.mock import MagicMock, patch

        import trading_gates
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.base_url = "https://api.elections.kalshi.com/trade-api/v2"

        with (
            patch.dict("os.environ", {"LIVE_TRADING_ENABLED": "true"}, clear=False),
            patch("trading_gates.is_trading_paused", return_value=False),
            patch("trading_gates.KILL_SWITCH_PATH") as mock_ks,
        ):
            mock_ks.exists.return_value = True
            with pytest.raises(RuntimeError, match="Kill switch"):
                trading_gates.pre_live_exit_check(mock_client)
            result = _exit_live_position(
                mock_client, self._position(), 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_not_called()

    def test_trading_paused_still_blocks_a_protective_exit(self):
        """Sibling of the kill-switch case -- the second of the two operator
        "touch nothing" instructions the reduced gate deliberately keeps."""
        from unittest.mock import MagicMock, patch

        import trading_gates

        mock_client = MagicMock()
        mock_client.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        with (
            patch.dict("os.environ", {"LIVE_TRADING_ENABLED": "true"}, clear=False),
            patch("trading_gates.is_trading_paused", return_value=True),
        ):
            with pytest.raises(RuntimeError, match="TRADING_PAUSED"):
                trading_gates.pre_live_exit_check(mock_client)

    def test_reduced_exit_gate_still_requires_the_real_money_interlocks(self):
        """The reduced gate drops RISK LIMITS, never the interlocks that
        decide whether this process may talk to the real exchange at all --
        otherwise a misconfigured demo/shadow run could fire real SELLs."""
        from unittest.mock import MagicMock, patch

        import trading_gates

        demo_client = MagicMock()
        demo_client.base_url = "https://demo-api.kalshi.co/trade-api/v2"
        prod_client = MagicMock()
        prod_client.base_url = "https://api.elections.kalshi.com/trade-api/v2"

        with (
            patch.dict("os.environ", {"LIVE_TRADING_ENABLED": "true"}, clear=False),
            patch("trading_gates.is_trading_paused", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="not pointed at prod"):
                trading_gates.pre_live_exit_check(demo_client)
            # Positive control: the same call with a prod client passes, so
            # the rejection above is the base_url check and nothing else.
            trading_gates.pre_live_exit_check(prod_client)

        with (
            patch.dict("os.environ", {"LIVE_TRADING_ENABLED": ""}, clear=False),
            patch("trading_gates.is_trading_paused", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
                trading_gates.pre_live_exit_check(prod_client)

    def test_gate_blocked_exit_fires_an_operator_alert(self):
        """Batch-58 item 4: a blocked exit means an open position cannot be
        closed automatically -- that must reach an operator, not only the
        log. Paired with a negative control: an ALLOWED exit must not fire
        the alert, so this cannot pass by the alert being unconditional."""
        from unittest.mock import MagicMock, patch

        from order_executor import _exit_live_position

        mock_client = MagicMock()
        with (
            patch(
                "trading_gates.pre_live_exit_check",
                side_effect=RuntimeError("Kill switch active (data/.kill_switch)"),
            ),
            patch("notify.send_system_alert") as mock_alert,
        ):
            _exit_live_position(
                mock_client, self._position(), 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert mock_alert.called
        _title, _message = mock_alert.call_args.args
        assert "Kill switch" in _message
        assert mock_alert.call_args.kwargs["cooldown_key"] == "live_exit_blocked"

        allowed_client = MagicMock()
        allowed_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            _live_gates_open(),
            patch("notify.send_system_alert") as mock_alert_ok,
        ):
            _exit_live_position(
                allowed_client,
                self._position_with_row(),
                0.20,
                "stop_loss",
                "2026-05-15_12z",
            )
        mock_alert_ok.assert_not_called()

    def test_exit_cycle_key_scoped_to_this_attempts_log_id(self):
        """AUD batch-23 #1: NOT the bare forecast cycle -- a protective exit
        that doesn't fill (illiquid book) must be able to actually retry
        with a fresh key, not one that would dedupe against itself."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        cycle_arg = mock_client.place_order.call_args.kwargs["cycle"]
        assert cycle_arg != "2026-05-15_12z"
        assert cycle_arg.startswith("2026-05-15_12z:exit:")

    def test_repeated_unfilled_exit_attempts_get_distinct_cycle_keys(self):
        """The exact collision this fix closes: an IOC exit that doesn't
        fill (illiquid market) leaves the book, ticker, side, exit_price,
        and forecast cycle all unchanged for a retry on the next cycle
        scan -- prior to this fix, that retry would regenerate the SAME
        client_order_id as the first no-op attempt and Kalshi would dedupe
        it, so the protective exit could never actually be re-placed."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit_1",
            "fill_count_fp": "0.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result1 = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )
        assert result1 is False  # unfilled IOC -- position remains open
        first_cycle = mock_client.place_order.call_args.kwargs["cycle"]

        mock_client.place_order.return_value = {
            "order_id": "ord_exit_2",
            "fill_count_fp": "0.00",
        }
        with _live_gates_open():
            _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )
        second_cycle = mock_client.place_order.call_args.kwargs["cycle"]

        assert first_cycle != second_cycle

    def test_prelogged_client_order_id_matches_wire_cid(self):
        """Batch-31 CR-1: the pre-logged client_order_id must be
        byte-identical to the one place_order() actually sends. Previously
        the pre-log computation used the BARE cycle while place_order()
        itself derived its key from the exit-scoped cycle
        (f"{cycle}:exit:{log_id}") -- a crash in the window between the
        pre-log write and log_order_result recording the real outcome (the
        live-order watchdog's os._exit(1) can land exactly there) then made
        crash recovery re-check the WRONG id, get a confirmed negative, and
        mark a REAL protective SELL 'failed'. Because settled_at stayed NULL
        forever, the exit scanner then placed a fresh real SELL every cycle
        against an already-sold position, permanently consuming a
        max_open_positions slot.

        Unlike _replace_live_order's single-step pre-log, _exit_live_position
        needs the row's own log_id (unknown before the row exists) to build
        the scoped cycle -- so the pre-log is two calls: log_order() then
        log_order_result() writing the real cid. Spies on log_order_result
        and captures its FIRST call's response= kwarg (the pre-wire write --
        a second log_order_result call happens later with the wire response,
        which would overwrite it), and independently re-derives the expected
        id from the cycle/time_in_force place_order() actually received."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from kalshi_client import compute_client_order_id
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_cid_check",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        real_log_order_result = execution_log.log_order_result
        result_calls = []

        def _spy_log_order_result(*args, **kwargs):
            result_calls.append(kwargs)
            return real_log_order_result(*args, **kwargs)

        position = self._position(id=row_id)
        with (
            patch.object(
                execution_log,
                "log_order_result",
                side_effect=_spy_log_order_result,
            ),
            _live_gates_open(),
        ):
            _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        posted_cycle = mock_client.place_order.call_args.kwargs["cycle"]
        posted_tif = mock_client.place_order.call_args.kwargs["time_in_force"]
        expected_cid = compute_client_order_id(
            "KXHIGH-25MAY15-T75", "yes", "sell", 10, 0.20, posted_tif, posted_cycle
        )

        prelog_calls = [c for c in result_calls if c.get("response") is not None]
        assert len(prelog_calls) >= 1, "no log_order_result call carried a response"
        assert prelog_calls[0]["response"]["client_order_id"] == expected_cid

    def test_claim_blocks_a_concurrent_scanner_on_the_same_position(self):
        """Batch-31 M-4: cron's and watch's exit scanners are deliberately
        NOT serialized (AUD-0013) and each independently derives the
        identical exit decision for the same position -- without a claim,
        both could call place_order() and both real SELLs could land. The
        loser must skip the position entirely (return False, place_order
        never called), not race into it."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        # Simulate a concurrent scanner having already won the claim for
        # this position (e.g. cron's cycle claimed it a moment before
        # watch's own standalone call reached the same position).
        assert execution_log.claim_position_for_exit(row_id) is not None

        mock_client = MagicMock()
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_not_called()

    def test_claim_released_after_unfilled_ioc_allows_immediate_retry(self):
        """An illiquid-market no-fill must not block the SAME scanner's own
        next-cycle retry for claim_position_for_exit's full TTL -- the claim
        is released as soon as this attempt confirms it didn't close
        anything, matching the existing dedup-key test's expectation that
        two sequential no-fill attempts on the same position both actually
        reach place_order()."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "0.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )
        # Positive control (independent review, batch-31 F7): the claim
        # actually being taken and released this run, not e.g. the row
        # never having been claimed in the first place because some earlier
        # return path short-circuited before reaching claim_position_for_exit.
        mock_client.place_order.assert_called_once()
        # Claim must be gone -- a fresh claim attempt now succeeds.
        assert execution_log.claim_position_for_exit(row_id) is not None

    def test_claim_retained_after_order_status_unknown(self):
        """Batch-31 M-4: an OrderStatusUnknownError outcome's true fate is
        unconfirmed (AUD-0007) -- releasing the claim here would reopen the
        exact double-sell window the claim exists to close, so unlike the
        no-fill/failed cases, the claim must stay held (a second immediate
        attempt is blocked) until the TTL expires or the row settles."""
        from unittest.mock import MagicMock

        import execution_log
        from kalshi_client import OrderStatusUnknownError
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.side_effect = OrderStatusUnknownError(
            "some-cid", ConnectionError("timeout")
        )
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        # Positive control (independent review, batch-31 F7): the attempt
        # actually reached place_order() and hit the unknown-outcome path,
        # not some earlier return that happens to also leave the claim held.
        mock_client.place_order.assert_called_once()
        # Claim must still be held -- an immediate re-claim attempt fails.
        assert execution_log.claim_position_for_exit(row_id) is None

    def test_claim_released_after_confirmed_placement_failure(self):
        """A confirmed-not-landed placement failure (place_order raises a
        plain Exception, not OrderStatusUnknownError) is safe to release
        immediately for a retry next scan."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.side_effect = ConnectionError("confirmed down")
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        assert execution_log.claim_position_for_exit(row_id) is not None

    def test_full_fill_records_fee_adjusted_pnl(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is True
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert kwargs["action"] == "sell"
        assert kwargs["time_in_force"] == "immediate_or_cancel"
        assert kwargs["price"] == pytest.approx(0.20)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, exit_price, exit_reason, pnl, outcome_yes "
                "FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        # Batch-22 items 3+6: fee applies on a loss too now (charged on the
        # taker fill itself, independent of outcome). gross_pnl = 10 *
        # (0.20 - 0.40) = -2.00; fee = ceil(0.07*10*0.20*0.80*100)/100 =
        # 0.12. pnl = -2.00 - 0.12 = -2.12.
        assert row["pnl"] == pytest.approx(-2.12)
        assert row["exit_price"] == pytest.approx(0.20)
        assert row["exit_reason"] == "stop_loss"
        assert row["outcome_yes"] is None
        assert row["settled_at"] is not None

    def test_full_fill_exit_order_not_treated_as_new_open_position(self):
        """Regression pin for the phantom-position bug on the FULL-fill
        path specifically (the partial-fill tests already pin it for that
        branch) -- a refactor that moved closes_position_id into only the
        partial branch would silently reopen this gap for full exits, which
        are the common case."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position, _get_live_open_positions

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )
        assert result is True
        # Positive control: the exit order row itself really was logged
        # live/filled (the shape that would trigger the bug if unguarded).
        with execution_log._conn() as con:
            exit_row = con.execute(
                "SELECT live, status, settled_at, closes_position_id FROM orders "
                "WHERE id != ? ORDER BY id DESC LIMIT 1",
                (row_id,),
            ).fetchone()
        assert exit_row["live"] == 1
        assert exit_row["status"] == "filled"
        assert exit_row["settled_at"] is None
        assert exit_row["closes_position_id"] == row_id
        # The actual guard: no phantom position surfaces afterward.
        assert _get_live_open_positions() == []

    def test_gain_case_applies_fee_discount(self):
        """A genuine gain (exit_price > entry_price, e.g. a model-exit that
        fires on a favorable move) DOES get the taker-fee discount -- and
        (batch-22 items 3+6) so does a loss, since the fee is charged on the
        taker fill itself regardless of outcome."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.60, "model_exit", "2026-05-15_12z"
            )

        assert result is True
        # gross_pnl = 10 * (0.60 - 0.40) = 2.00; fee = ceil(0.07*10*0.60*
        # 0.40*100)/100 = 0.17. pnl = 2.00 - 0.17 = 1.83.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT pnl FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["pnl"] == pytest.approx(1.83)

    def test_ioc_no_fill_leaves_position_open(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "0.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        # Original position row must still read as open (settled_at untouched).
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["settled_at"] is None

    def test_partial_fill_reconciles_quantity_and_realizes_pnl(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        # Not fully closed -- the remaining 6 contracts stay open for a
        # future cycle's protective-exit attempt.
        assert result is False
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, fill_quantity FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        # Must not silently mark the position fully closed, which would
        # corrupt the ledger by claiming 10 contracts exited when only 4
        # actually did.
        assert row["settled_at"] is None
        # But the tracked open quantity IS reduced by exactly the filled
        # amount, so a re-read sees only the genuine remainder as open.
        assert row["fill_quantity"] == 6
        # Positive control: the reduced position still surfaces as open.
        reopened = execution_log.get_filled_unsettled_live_orders()
        assert len(reopened) == 1
        assert reopened[0]["fill_quantity"] == 6

        # gross_pnl = 4 * (0.20 - 0.40) = -0.80; fee = ceil(0.07*4*0.20*
        # 0.80*100)/100 = 0.05. pnl = -0.85, realized immediately via
        # add_live_loss even though the row itself isn't settled yet.
        assert execution_log.get_today_live_loss() == pytest.approx(0.85)

    def test_partial_fill_gain_case_applies_fee_discount(self):
        """Mirrors test_gain_case_applies_fee_discount for the partial-fill
        branch -- the sold portion's realized P&L must get the same
        gain-only fee discount as a full exit."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.60, "model_exit", "2026-05-15_12z"
            )

        assert result is False
        # gross_pnl = 4 * (0.60 - 0.40) = 0.80; fee = ceil(0.07*4*0.60*
        # 0.40*100)/100 = 0.07. pnl = 0.80 - 0.07 = 0.73.
        assert execution_log.get_today_live_loss() == pytest.approx(-0.73)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT fill_quantity FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["fill_quantity"] == 6

    def test_place_order_exception_logs_failed_status(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.side_effect = ConnectionError("down")
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        rows = execution_log.get_recent_orders(limit=10)
        failed_row = next(r for r in rows if r["status"] == "failed")
        assert failed_row is not None

    def test_no_side_exit_pnl_uses_no_side_prices_directly(self):
        """entry_price/exit_price are already side-normalized (see
        _midpoint_price/_liquidation_price) -- the pnl formula must not
        re-derive a yes-price conversion for the "no" side."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "5.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=5,
            price=0.30,
            status="filled",
            live=True,
        )
        position = self._position(
            id=row_id, side="no", entry_price=0.30, quantity=5, cost=1.5
        )
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.15, "stop_loss", "2026-05-15_12z"
            )

        assert result is True
        # gross_pnl = 5 * (0.15 - 0.30) = -0.75; fee = ceil(0.07*5*0.15*
        # 0.85*100)/100 = 0.05. pnl = -0.75 - 0.05 = -0.80.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT pnl FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["pnl"] == pytest.approx(-0.80)

    def test_partial_fill_settles_the_exit_orders_own_row(self):
        """L1378: a partial IOC exit must settle its OWN row (not the
        position row, which must stay open for the remainder) so the sold
        lot gets a real pnl/settled_at instead of only ever landing in the
        daily aggregate total via add_live_loss."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "3.00",  # only 3 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with _live_gates_open():
            result = _exit_live_position(
                mock_client, position, 0.60, "model_exit", "2026-05-15_12z"
            )
        assert result is False

        with execution_log._conn() as con:
            exit_row = con.execute(
                "SELECT quantity, fill_quantity, settled_at, exit_price, "
                "exit_reason, pnl FROM orders WHERE closes_position_id = ?",
                (row_id,),
            ).fetchone()
        # Requested qty (10, the whole remaining position at the time) is
        # NOT the same as what actually sold (3) -- export_live_tax_csv must
        # read fill_quantity, not quantity, for this row.
        assert exit_row["quantity"] == 10
        assert exit_row["fill_quantity"] == 3
        assert exit_row["settled_at"] is not None
        assert exit_row["exit_price"] == pytest.approx(0.60)
        assert exit_row["exit_reason"] == "model_exit"
        # gross_pnl = 3 * (0.60 - 0.40) = 0.60; fee = ceil(0.07*3*0.60*
        # 0.40*100)/100 = 0.06. pnl = 0.60 - 0.06 = 0.54.
        assert exit_row["pnl"] == pytest.approx(0.54)

    def test_partial_then_full_exit_combined_pnl_not_under_reported(self, tmp_path):
        """Regression for L1378: a position sold in two legs (a partial IOC
        exit, then a later full exit of the remainder) must have BOTH legs'
        pnl counted in get_live_pnl_summary/export_live_tax_csv, not just
        the final leg -- proves the fix closes the exact gap the entry
        described, not just that some pnl shows up somewhere."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        # Leg 1: partial exit, gain. gross = 3*(0.60-0.40)=0.60, fee =
        # ceil(0.07*3*0.60*0.40*100)/100 = 0.06. pnl = 0.60 - 0.06 = 0.54.
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_partial",
            "fill_count_fp": "3.00",
        }
        position = self._position(id=row_id, quantity=10)
        with _live_gates_open():
            leg1_result = _exit_live_position(
                mock_client, position, 0.60, "model_exit", "2026-05-15_12z"
            )
        assert leg1_result is False
        partial_pnl = 0.54

        # Leg 2: full exit of the reduced remainder (7 left), loss. gross =
        # 7*(0.30-0.40)=-0.70; fee = ceil(0.07*7*0.30*0.70*100)/100 = 0.11
        # (batch-22 items 3+6: fee now applies on a loss too). pnl = -0.81.
        mock_client2 = MagicMock()
        mock_client2.place_order.return_value = {
            "order_id": "ord_final",
            "fill_count_fp": "7.00",
        }
        position2 = self._position(id=row_id, quantity=7)
        with _live_gates_open():
            leg2_result = _exit_live_position(
                mock_client2, position2, 0.30, "stop_loss", "2026-05-15_12z"
            )
        assert leg2_result is True
        final_pnl = -0.81

        summary = execution_log.get_live_pnl_summary()
        # The core assertion: the combined total, not just the final leg.
        assert summary["total_pnl"] == pytest.approx(partial_pnl + final_pnl)
        # Pin the exact size of the gap the un-fixed code would have left:
        # pre-fix, total_pnl would have been final_pnl alone (the partial
        # leg's row was never settled), silently dropping partial_pnl.
        assert summary["total_pnl"] != pytest.approx(final_pnl)
        gap = summary["total_pnl"] - final_pnl
        assert gap == pytest.approx(partial_pnl)
        assert summary["settled_count"] == 2

        out_path = str(tmp_path / "live_tax.csv")
        count = execution_log.export_live_tax_csv(out_path)
        assert count == 2
        import csv

        with open(out_path, newline="") as f:
            rows = list(csv.DictReader(f))
        rows_by_pnl = {round(float(r["pnl"]), 3): r for r in rows}
        partial_row = rows_by_pnl[round(partial_pnl, 3)]
        final_row = rows_by_pnl[round(final_pnl, 3)]
        # Both legs must report the TRUE entry price (0.40), not the
        # partial leg's own row price (which is its exit price, 0.60).
        assert partial_row["entry_price"] == "0.4"
        assert final_row["entry_price"] == "0.4"
        # The partial leg's quantity must be the actual sold amount (3),
        # not the requested IOC qty at the time (10).
        assert partial_row["quantity"] == "3"
        assert final_row["quantity"] == "7"
        assert partial_row["outcome"] == "early_exit"
        assert final_row["outcome"] == "early_exit"

    def test_two_partial_fills_then_final_close_all_three_legs_counted(self):
        """N partial fills before a final close must each settle their OWN
        exit-order row -- not just the first one -- since every
        _exit_live_position call creates a fresh log_order row regardless of
        how many partial legs already happened against the same position."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _exit_live_position

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

        # Leg 1: partial, gain. gross=3*(0.60-0.40)=0.60, fee=ceil(0.07*3*
        # 0.60*0.40*100)/100=0.06, pnl=0.54.
        mock1 = MagicMock()
        mock1.place_order.return_value = {"order_id": "ord1", "fill_count_fp": "3.00"}
        with _live_gates_open():
            r1 = _exit_live_position(
                mock1,
                self._position(id=row_id, quantity=10),
                0.60,
                "model_exit",
                "2026-05-15_12z",
            )
        assert r1 is False
        pnl1 = 0.54

        # Leg 2: partial, loss. gross=4*(0.30-0.40)=-0.40; fee=ceil(0.07*4*
        # 0.30*0.70*100)/100=0.06 (batch-22 items 3+6: fee now applies on a
        # loss too). pnl=-0.46.
        mock2 = MagicMock()
        mock2.place_order.return_value = {"order_id": "ord2", "fill_count_fp": "4.00"}
        with _live_gates_open():
            r2 = _exit_live_position(
                mock2,
                self._position(id=row_id, quantity=7),
                0.30,
                "stop_loss",
                "2026-05-15_12z",
            )
        assert r2 is False
        pnl2 = -0.46

        # Leg 3: final close of the last 3. gross=3*(0.50-0.40)=0.30, fee=
        # ceil(0.07*3*0.50*0.50*100)/100=0.06, pnl=0.24.
        mock3 = MagicMock()
        mock3.place_order.return_value = {"order_id": "ord3", "fill_count_fp": "3.00"}
        with _live_gates_open():
            r3 = _exit_live_position(
                mock3,
                self._position(id=row_id, quantity=3),
                0.50,
                "model_exit",
                "2026-05-15_12z",
            )
        assert r3 is True
        pnl3 = 0.24

        summary = execution_log.get_live_pnl_summary()
        assert summary["total_pnl"] == pytest.approx(pnl1 + pnl2 + pnl3)
        assert summary["settled_count"] == 3

        with execution_log._conn() as con:
            # The final leg's own exit-order row is deliberately left
            # unsettled (its pnl lands on the position row instead, same as
            # any full-exit) -- filter to settled rows to isolate the two
            # partial legs' own rows.
            exit_rows = con.execute(
                "SELECT pnl FROM orders WHERE closes_position_id = ? "
                "AND pnl IS NOT NULL ORDER BY placed_at",
                (row_id,),
            ).fetchall()
        # Both partial legs' own rows settled independently -- not just leg 1.
        assert [round(r["pnl"], 3) for r in exit_rows] == [
            round(pnl1, 3),
            round(pnl2, 3),
        ]


class TestCheckLivePositionExits(_LiveDBTestBase):
    def _open_position_row(self, ticker="KXHIGH-25MAY15-T75", **overrides):
        from datetime import UTC, datetime, timedelta

        import execution_log

        defaults = dict(
            ticker=ticker,
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
            # Well beyond the 24h pre-settlement gate check_stop_losses/
            # check_breakeven_stops both apply.
            close_time=(datetime.now(UTC) + timedelta(days=10)).isoformat(),
        )
        defaults.update(overrides)
        row_id = execution_log.log_order(**defaults)
        execution_log.log_order_result(
            row_id, status="filled", fill_quantity=defaults["quantity"]
        )
        return row_id

    def test_no_open_positions_is_a_no_op(self):
        from unittest.mock import MagicMock

        from order_executor import _check_live_position_exits

        mock_client = MagicMock()
        _check_live_position_exits(mock_client)  # must not raise
        mock_client.place_order.assert_not_called()

    def test_stop_loss_breach_triggers_immediate_exit(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # Loss > cost / STOP_LOSS_MULT (default 2.0) -> unrealized loss > 50% of cost.
        # cost = 5.0, bid=0.10 -> unrealized_pnl = (0.10-0.50)*10 = -4.0 < -2.5 -> fires.
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            _live_gates_open(),
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["exit_reason"] == "stop_loss"
        assert row["settled_at"] is not None

    def test_stop_loss_fires_on_rest_fallback_integer_cents_book(self):
        """Regression: _get_current_book's REST fallback returns the raw
        client.get_market() dict unchanged (integer cents, e.g. yes_bid=10,
        not the dollar float 0.10 the WS-cache path returns) -- this is the
        realistic shape for every cron run, since a fresh process starts
        with an empty WS cache. Reading it without normalizing through
        utils.coalesce_market_price would treat 10 as a $10 price, making the
        position look wildly profitable and never trigger the stop."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # Raw get_market()-shaped dict, integer cents -- the real REST-fallback
        # shape, not the pre-normalized dollar floats the other tests mock.
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 10, "yes_ask": 15},
            ),
            _live_gates_open(),
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["exit_reason"] == "stop_loss"
        assert row["settled_at"] is not None

    def test_healthy_position_is_left_alone(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _check_live_position_exits

        self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        with patch(
            "order_executor._get_current_book",
            return_value={"yes_bid": 0.52, "yes_ask": 0.57},
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_not_called()

    def test_stop_loss_and_breakeven_are_mutually_exclusive_same_cycle(self):
        """A ticker that stop-loss-exits must not also be evaluated for a
        breakeven exit in the same call — it's already closed (or a real
        exit attempt already happened)."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)
        # Simulate a pre-existing peak high enough to arm breakeven too.
        execution_log.update_live_peak_profit(row_id, 0.50)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            _live_gates_open(),
        ):
            _check_live_position_exits(mock_client)

        # Only the stop-loss exit should have fired, not a second breakeven exit.
        assert mock_client.place_order.call_count == 1

    def test_two_positions_on_same_ticker_both_get_exited(self):
        """Regression: two separate open live positions sharing a ticker
        (two distinct fills before either settles) must both be protected --
        a naive ticker-keyed dict would collapse them and silently leave one
        with zero protection."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id_a = self._open_position_row(price=0.50, quantity=10)
        row_id_b = self._open_position_row(price=0.55, quantity=5)
        assert row_id_a != row_id_b

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # bid=0.10 breaches stop-loss for both positions independently
        # (well past 50% of either position's cost).
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            _live_gates_open(),
        ):
            _check_live_position_exits(mock_client)

        assert mock_client.place_order.call_count == 2
        with execution_log._conn() as con:
            rows = con.execute(
                "SELECT id, exit_reason, settled_at FROM orders WHERE id IN (?, ?)",
                (row_id_a, row_id_b),
            ).fetchall()
        for row in rows:
            assert row["exit_reason"] == "stop_loss"
            assert row["settled_at"] is not None

    def test_two_positions_same_ticker_only_one_individually_breaches_both_exit(self):
        """The fan-out safety property this ticket-level by_ticker grouping
        exists for: when only ONE of two same-ticker positions individually
        breaches its own stop-loss threshold, BOTH must still be exited --
        erring toward protecting a position that didn't strictly need to
        exit yet, rather than risk leaving position B's zero-protection gap
        the ticket-collapse regression test above guards against. Without
        the by_ticker fan-out (e.g. if a future 'simplification' exited
        only the position(s) check_stop_losses itself returned), this would
        exit A but silently leave B open."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        # A: cost=5.0, threshold=-2.5 -> at bid=0.10, pnl=(0.10-0.50)*10=-4.0 -> breaches.
        row_id_a = self._open_position_row(price=0.50, quantity=10)
        # B: cost=1.2, threshold=-0.6 -> at the SAME bid=0.10, pnl=(0.10-0.12)*10=-0.2
        # -> does NOT individually breach.
        row_id_b = self._open_position_row(price=0.12, quantity=10)
        assert row_id_a != row_id_b

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            _live_gates_open(),
        ):
            _check_live_position_exits(mock_client)

        assert mock_client.place_order.call_count == 2
        with execution_log._conn() as con:
            rows = con.execute(
                "SELECT id, exit_reason, settled_at FROM orders WHERE id IN (?, ?)",
                (row_id_a, row_id_b),
            ).fetchall()
        for row in rows:
            assert row["exit_reason"] == "stop_loss"
            assert row["settled_at"] is not None


class TestCheckLiveModelExits(_LiveDBTestBase):
    def _open_position_row(self, ticker="KXHIGH-25MAY15-T75", **overrides):
        from datetime import UTC, datetime, timedelta

        import execution_log

        defaults = dict(
            ticker=ticker,
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
            # Well beyond the 24h pre-settlement gate.
            close_time=(datetime.now(UTC) + timedelta(days=10)).isoformat(),
            entry_prob=0.65,
        )
        defaults.update(overrides)
        row_id = execution_log.log_order(**defaults)
        # Backdate the fill past the 12h minimum-hold gate -- log_order_result
        # without an explicit filled_at leaves entered_at falling back to
        # placed_at, which log_order stamps at "now" (this test run), always
        # failing the 12h gate otherwise.
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=defaults["quantity"],
            filled_at=(datetime.now(UTC) - timedelta(hours=48)).isoformat(),
        )
        return row_id

    def test_no_client_returns_zero(self):
        from order_executor import _check_live_model_exits

        assert _check_live_model_exits(None) == 0

    def test_missing_entry_prob_is_skipped(self):
        from unittest.mock import MagicMock

        from order_executor import _check_live_model_exits

        self._open_position_row(entry_prob=None)
        mock_client = MagicMock()
        mock_client.get_markets.return_value = []
        assert _check_live_model_exits(mock_client) == 0
        mock_client.place_order.assert_not_called()

    def test_model_flip_beyond_threshold_triggers_exit(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_model_exits

        row_id = self._open_position_row(entry_prob=0.65)

        market = {
            "ticker": "KXHIGH-25MAY15-T75",
            "close_time": "2026-06-01T12:00:00+00:00",
            "yes_bid": "0.30",
            "yes_ask": "0.35",
        }
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch("order_executor.get_weather_markets", return_value=[market]),
            patch("order_executor.enrich_with_forecast", return_value={"_raw": market}),
            # entry_prob=0.65, current=0.35 -> shift = 0.65-0.35 = 0.30 > 0.25
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.35},
            ),
            patch("order_executor._get_current_book", return_value=None),
            _live_gates_open(),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 1
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["exit_reason"] == "model_exit"

    def test_within_settlement_gate_skips_exit(self):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        from order_executor import _check_live_model_exits

        # close_time only 1 hour away -- inside the 24h pre-settlement gate.
        close_soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        self._open_position_row(
            entry_prob=0.65,
            close_time=close_soon,
        )
        market = {"ticker": "KXHIGH-25MAY15-T75"}
        mock_client = MagicMock()
        with (
            patch("order_executor.get_weather_markets", return_value=[market]),
            patch("order_executor.enrich_with_forecast", return_value={"_raw": market}),
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.35},
            ),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 0
        mock_client.place_order.assert_not_called()

    def test_closes_correct_position_among_multiple_open(self):
        """AUD-0018-adjacent (batch-18): _check_live_model_exits now sources
        positions via LivePositionStore/_live_dict_to_position (positions.py's
        shared Position read-model) instead of reading _get_live_open_
        positions()'s raw dict fields directly. With two open positions where
        only one's shift clears MODEL_EXIT_SHIFT_PP, this proves the
        Position-based sourcing still targets the RIGHT row when closing --
        a list/dict misalignment bug in the refactor would either close the
        wrong ticker or close both."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_model_exits

        row_a = self._open_position_row(ticker="KXHIGH-25MAY15-FLIP", entry_prob=0.65)
        row_b = self._open_position_row(ticker="KXHIGH-25MAY15-HOLD", entry_prob=0.65)

        market_a = {
            "ticker": "KXHIGH-25MAY15-FLIP",
            "close_time": "2026-06-01T12:00:00+00:00",
            "yes_bid": "0.30",
            "yes_ask": "0.35",
        }
        market_b = {
            "ticker": "KXHIGH-25MAY15-HOLD",
            "close_time": "2026-06-01T12:00:00+00:00",
            "yes_bid": "0.62",
            "yes_ask": "0.66",
        }

        def _fake_analyze(enriched):
            # entry_prob=0.65 for both; FLIP shifts 0.30 (>0.25 threshold),
            # HOLD shifts only 0.05 (stays open).
            if enriched.get("ticker") == "KXHIGH-25MAY15-FLIP":
                return {"forecast_prob": 0.35}
            return {"forecast_prob": 0.60}

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch(
                "order_executor.get_weather_markets",
                return_value=[market_a, market_b],
            ),
            patch("order_executor.enrich_with_forecast", side_effect=lambda m: m),
            patch("order_executor.analyze_trade", side_effect=_fake_analyze),
            patch("order_executor._get_current_book", return_value=None),
            _live_gates_open(),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 1
        with execution_log._conn() as con:
            row_a_data = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?", (row_a,)
            ).fetchone()
            row_b_data = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?", (row_b,)
            ).fetchone()
        assert row_a_data["exit_reason"] == "model_exit", (
            "the FLIP position (real shift > threshold) must be the one closed"
        )
        assert row_b_data["exit_reason"] is None and row_b_data["settled_at"] is None, (
            "the HOLD position (shift under threshold) must remain open -- a "
            "list/dict misalignment bug would close this one instead of/as "
            "well as FLIP"
        )

    def test_one_malformed_raw_position_does_not_drop_others(self, caplog):
        """Opus review finding (batch-18): _live_dict_to_position is now
        called per-item inside the loop, not via a list comprehension
        batched ahead of it -- a batched
        `[_live_dict_to_position(d) for d in raw_positions]` would raise on
        the FIRST malformed dict (missing "quantity", which
        _live_dict_to_position subscripts unguarded) before the loop even
        starts, dropping every other -- otherwise perfectly fine -- position
        for that whole cycle. The "good" position is a REAL execution_log
        row (via _open_position_row), not a synthetic dict, so closing it
        actually exercises record_live_exit_fill's DB update rather than
        risking an unrelated crash from a nonexistent row id. Also asserts
        the malformed position was logged, not silently swallowed
        (round-2 opus review INFO finding)."""
        from unittest.mock import MagicMock, patch

        from order_executor import _check_live_model_exits, _get_live_open_positions

        self._open_position_row(ticker="KXHIGH-GOOD", entry_prob=0.65)
        real_positions = _get_live_open_positions()
        assert len(real_positions) == 1

        bad_position = {
            "id": 9001,
            "ticker": "KXHIGH-BAD",
            "side": "yes",
            "entry_price": 0.50,
            "cost": 5.0,
            "entry_prob": 0.65,
            # "quantity" deliberately missing -- triggers the unguarded
            # d["quantity"] subscript in _live_dict_to_position.
        }
        market_good = {
            "ticker": "KXHIGH-GOOD",
            "close_time": "2026-06-01T12:00:00+00:00",
            "yes_bid": "0.30",
            "yes_ask": "0.35",
        }

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch(
                "order_executor._get_live_open_positions",
                return_value=[bad_position, *real_positions],
            ),
            patch("order_executor.get_weather_markets", return_value=[market_good]),
            patch("order_executor.enrich_with_forecast", side_effect=lambda m: m),
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.35},  # shift 0.30 > threshold
            ),
            patch("order_executor._get_current_book", return_value=None),
            _live_gates_open(),
            caplog.at_level("WARNING"),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 1, (
            "the good position (listed after the malformed one) must still be closed"
        )
        assert "[LiveModelExit] Error checking" in caplog.text, (
            "the malformed position must be logged, not silently dropped"
        )


class TestUnresolvedOrderAgeCap:
    """Batch-58 item 5 (backlog L24457): an 'unknown' live order whose true
    state genuinely could not be determined was re-checked forever -- 3
    authenticated GETs per recovery pass, with no age cap, no terminal state
    and no escalation of any kind. It now alerts an operator once and parks
    at the terminal 'unresolved' status."""

    def _unknown_row(self, age_minutes, *, client_order_id="coid_stuck"):
        from datetime import UTC, datetime, timedelta

        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="unknown",
            live=True,
            response=({"client_order_id": client_order_id} if client_order_id else {}),
        )
        placed = datetime.now(UTC) - timedelta(minutes=age_minutes)
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?",
                (placed.isoformat(), row_id),
            )
        return row_id

    def _client_that_cannot_resolve(self):
        """A client whose lookup completes but matches nothing, with
        uncertain=True -- i.e. the row genuinely stays unknown."""
        from unittest.mock import MagicMock

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        return client

    def test_a_fresh_unresolvable_row_is_left_alone(self):
        """Negative control for the age cap. Without this, the parking test
        below could pass simply because EVERY unresolvable row gets parked,
        which would abandon rows that are only transiently unresolvable."""
        from unittest.mock import patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=5)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(self._client_that_cannot_resolve())

        assert execution_log.get_order_by_id(row_id)["status"] == "unknown"
        mock_alert.assert_not_called()

    def test_a_stale_row_alerts_but_is_not_parked_when_the_lookup_failed(self):
        """Opus review (batch-58, L2): _client_that_cannot_resolve models a
        FAILING lookup (uncertain=True), which is the state where the bot
        cannot tell whether the order landed. Escalate, but keep retrying --
        abandoning a possibly-real order because our own API access is
        broken is the wrong failure direction."""
        from unittest.mock import patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=60 * 48)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(self._client_that_cannot_resolve())

        assert execution_log.get_order_by_id(row_id)["status"] == "unknown"
        assert execution_log.get_unresolved_live_orders() == []
        assert mock_alert.called
        title, message = mock_alert.call_args.args
        assert "lookup failing" in title.lower()
        assert "coid_stuck" in message
        assert (
            mock_alert.call_args.kwargs["cooldown_key"]
            == f"unresolved_live_order:{row_id}"
        )

    def test_a_fresh_row_does_not_alert_even_when_the_lookup_failed(self):
        """Negative control for the age cap on the uncertain path -- a
        transient outage must not page anyone."""
        from unittest.mock import patch

        from order_executor import _recover_pending_orders

        self._unknown_row(age_minutes=5)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(self._client_that_cannot_resolve())
        mock_alert.assert_not_called()

    def test_a_parked_row_is_never_polled_again(self):
        """The performance half of the fix: the recovery pass must stop
        spending API round-trips on a row it has already given up on.

        Uses a no-client_order_id row, which is the genuinely
        certain-and-unresolvable case -- there is no handle to re-check by,
        the lookup is not failing, and nothing about waiting longer can
        change the answer."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=60 * 48, client_order_id=None)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert"):
            _recover_pending_orders(client)
        assert execution_log.get_order_by_id(row_id)["status"] == "unresolved"

        client._find_orders_by_client_ids.reset_mock()
        with patch("notify.send_system_alert"):
            _recover_pending_orders(client)
        # Nothing left in the unknown queue -> the batched lookup is never
        # even reached on the second pass.
        client._find_orders_by_client_ids.assert_not_called()

    def test_a_row_that_resolves_this_pass_is_never_parked(self):
        """However old it is. Parking is terminal and operator-visible, so
        it must only ever happen to a row that actually failed to resolve."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=60 * 48)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(
            {"order_id": "ord_found", "status": "executed", "fill_count_fp": "10.00"},
            False,
        )
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "filled"
        mock_alert.assert_not_called()

    def test_a_stale_row_with_no_client_order_id_is_parked(self):
        """This branch was the worst dead end before the fix: it had no
        handle to re-check by at all, so it logged the same warning on every
        pass, forever."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=60 * 48, client_order_id=None)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)

        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unresolved"
        assert "MISSING" in mock_alert.call_args.args[1]

    def test_a_fresh_row_with_no_client_order_id_is_left_alone(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=5, client_order_id=None)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)

        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unknown"
        mock_alert.assert_not_called()

    def test_park_is_atomic_against_a_concurrent_resolution(self):
        """park_unresolved_order mirrors claim_unknown_order/claim_sent_order:
        the status predicate is what stops a losing pass reverting a row a
        concurrent process just resolved, and what makes the alert fire
        exactly once per row rather than once per process."""
        import execution_log

        row_id = self._unknown_row(age_minutes=60 * 48)
        assert execution_log.park_unresolved_order(row_id) is True
        # Second attempt loses: the row is no longer 'unknown'.
        assert execution_log.park_unresolved_order(row_id) is False

        execution_log.log_order_result(row_id, status="filled")
        assert execution_log.park_unresolved_order(row_id) is False
        assert execution_log.get_order_by_id(row_id)["status"] == "filled"

    def test_parking_preserves_the_stored_client_order_id(self):
        """It is the only handle an operator has for reconciling the row by
        hand, so parking must not touch response."""
        import json

        import execution_log

        row_id = self._unknown_row(age_minutes=60 * 48)
        execution_log.park_unresolved_order(row_id)

        row = execution_log.get_order_by_id(row_id)
        assert json.loads(row["response"])["client_order_id"] == "coid_stuck"

    def test_get_unresolved_live_orders_returns_parked_rows_only(self):
        import execution_log

        parked = self._unknown_row(age_minutes=60 * 48)
        still_unknown = self._unknown_row(age_minutes=5)
        execution_log.park_unresolved_order(parked)

        unresolved = execution_log.get_unresolved_live_orders()
        assert [r["id"] for r in unresolved] == [parked]
        # Positive control: the other row is still in the unknown queue, so
        # this is a real partition and not an empty-table artefact.
        assert [r["id"] for r in execution_log.get_unknown_live_orders()] == [
            still_unknown
        ]

    def test_a_parked_row_still_blocks_a_re_placement(self):
        """'unresolved' is deliberately NOT 'failed'. It appears on none of
        this module's dedup NOT-IN lists, so a parked row keeps blocking a
        retry exactly as it did while 'unknown' -- reusing 'failed' would
        have unblocked dedup and let the bot re-place an order that may be
        resting live on the exchange right now.

        Uses a row placed TODAY (parked directly rather than through the age
        cap) because both guards below are date-scoped."""
        import execution_log

        row_id = self._unknown_row(age_minutes=0)
        assert execution_log.park_unresolved_order(row_id) is True

        assert execution_log.was_traded_today("KXHIGH-25MAY15-T75", "yes", live=True)
        assert execution_log.was_recently_ordered(
            "KXHIGH-25MAY15-T75", "yes", within_minutes=60
        )

        # Positive control for the choice of terminal status: parked as
        # 'failed' instead, both guards would unblock an immediate retry.
        execution_log.log_order_result(row_id, status="failed")
        assert not execution_log.was_traded_today(
            "KXHIGH-25MAY15-T75", "yes", live=True
        )
        assert not execution_log.was_recently_ordered(
            "KXHIGH-25MAY15-T75", "yes", within_minutes=60
        )

    def test_a_parked_row_still_counts_toward_daily_live_spend(self):
        """Same reasoning as the dedup guards: get_today_live_spend's NOT-IN
        list excludes failed/canceled/cancelled/amended, so a parked row's
        capital stays counted. Dropping it would have silently loosened the
        daily spend cap at the moment the row became operator-actionable."""
        import execution_log

        row_id = self._unknown_row(age_minutes=0)
        before = execution_log.get_today_live_spend()
        assert before > 0

        assert execution_log.park_unresolved_order(row_id) is True
        assert execution_log.get_today_live_spend() == pytest.approx(before)

        # Positive control: 'failed' really does drop out of the total, so
        # the equality above is the status choice and not a no-op query.
        execution_log.log_order_result(row_id, status="failed")
        assert execution_log.get_today_live_spend() == pytest.approx(0.0)

    def test_an_unparseable_placed_at_does_not_park_or_crash(self):
        """Parking is terminal, so it must never happen on a guess."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=60 * 48, client_order_id=None)
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", ("not-a-date", row_id)
            )

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unknown"
        mock_alert.assert_not_called()

    def test_an_alert_failure_does_not_abort_the_recovery_pass(self):
        """The row is already parked by the time the alert is attempted, so
        a notify failure must not lose the rest of the pass."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_a = self._unknown_row(age_minutes=60 * 48, client_order_id=None)
        row_b = self._unknown_row(age_minutes=60 * 48, client_order_id=None)

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert", side_effect=RuntimeError("no net")):
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_a)["status"] == "unresolved"
        assert execution_log.get_order_by_id(row_b)["status"] == "unresolved"

    def test_the_age_threshold_is_configurable(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row(age_minutes=30, client_order_id=None)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with (
            patch.object(order_executor, "_UNRESOLVED_AGE_MINUTES", 10),
            patch("notify.send_system_alert"),
        ):
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unresolved"


class TestBatchedRecoveryLookup:
    """Batch-58 item 6 (backlog L24499), at the recovery-loop level: N unknown
    rows previously meant N full paginated walks of the account's order
    history per pass."""

    def _unknown_row(self, cid):
        import execution_log

        return execution_log.log_order(
            ticker=f"KXHIGH-25MAY15-T{70 + len(cid)}",
            side="yes",
            quantity=10,
            price=0.40,
            status="unknown",
            live=True,
            response={"client_order_id": cid},
        )

    def test_five_unknown_rows_cost_one_lookup_not_five(self):
        from unittest.mock import MagicMock

        from order_executor import _recover_pending_orders

        cids = [f"coid_{i}" for i in range(5)]
        for cid in cids:
            self._unknown_row(cid)

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        _recover_pending_orders(client)

        assert client._find_orders_by_client_ids.call_count == 1
        assert client._find_orders_by_client_ids.call_args.args[0] == set(cids)

    def test_each_row_still_resolves_to_its_own_matched_order(self):
        """The hoist must not cross-contaminate rows: each row is resolved
        from ITS OWN client_order_id's match, not the first one found."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_a = self._unknown_row("coid_a")
        row_b = self._unknown_row("coid_bb")

        client = MagicMock()
        client._find_orders_by_client_ids.return_value = (
            {
                "coid_a": {
                    "order_id": "ord_a",
                    "status": "executed",
                    "fill_count_fp": "10.00",
                },
                "coid_bb": {"order_id": "ord_b", "status": "resting"},
            },
            False,
        )
        _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_a)["status"] == "filled"
        assert execution_log.get_order_by_id(row_b)["status"] == "pending"

    def test_an_unmatched_row_is_confirmed_failed_only_when_certain(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._unknown_row("coid_gone")
        client = MagicMock()
        client._find_orders_by_client_ids.return_value = ({}, False)
        _recover_pending_orders(client)
        assert execution_log.get_order_by_id(row_id)["status"] == "failed"

        # Positive control: the same no-match result with uncertain=True must
        # NOT confirm the order failed -- a failed walk could be hiding it.
        row2 = self._unknown_row("coid_maybe")
        client2 = MagicMock()
        client2._find_orders_by_client_ids.return_value = ({}, True)
        _recover_pending_orders(client2)
        assert execution_log.get_order_by_id(row2)["status"] == "unknown"

    def test_a_lookup_that_raises_leaves_every_row_unknown(self):
        """_find_orders_by_client_ids handles per-walk failures itself, so a
        raise here is something more fundamental. It must degrade to
        uncertain (no row confirmed failed), not abort the pass."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_a = self._unknown_row("coid_a")
        row_b = self._unknown_row("coid_bb")

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = RuntimeError("boom")
        _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_a)["status"] == "unknown"
        assert execution_log.get_order_by_id(row_b)["status"] == "unknown"

    def test_rows_without_a_client_order_id_are_excluded_from_the_lookup_set(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        self._unknown_row("coid_ok")
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T99",
            side="yes",
            quantity=10,
            price=0.40,
            status="unknown",
            live=True,
            response={},
        )

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        _recover_pending_orders(client)

        assert client._find_orders_by_client_ids.call_args.args[0] == {"coid_ok"}


class TestUnresolvedRowExposure:
    """Batch-58 item 5, adjacency found during self-review: adding
    'unresolved' to _get_live_open_positions' include_unfilled union is only
    half the job -- the per-row quantity branch below it also had to learn
    the new status, or a parked row's exposure would silently SHRINK to its
    recorded partial fill at the exact moment it was parked."""

    def _row(self, status, quantity=10, fill_quantity=3):
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=quantity,
            price=0.40,
            status="pending",
            live=True,
        )
        execution_log.log_order_result(
            row_id, status=status, fill_quantity=fill_quantity
        )
        return row_id

    def test_a_parked_row_keeps_its_full_original_quantity(self):
        from order_executor import _get_live_open_positions

        self._row("unresolved", quantity=10, fill_quantity=3)
        positions = _get_live_open_positions(include_unfilled=True)

        assert len(positions) == 1
        # 10 (the full original exposure), NOT 3 (the recorded partial fill).
        assert positions[0]["quantity"] == 10

    def test_it_matches_what_pending_and_unknown_already_do(self):
        """Positive control: the three ACTIVE statuses must agree, so this
        cannot pass by 'unresolved' happening to be special-cased right
        while the shared reasoning drifted."""
        from order_executor import _get_live_open_positions

        for status in ("pending", "unknown", "unresolved"):
            self._row(status, quantity=10, fill_quantity=3)

        positions = _get_live_open_positions(include_unfilled=True)
        assert len(positions) == 3
        assert {p["quantity"] for p in positions} == {10}

    def test_a_filled_row_still_uses_its_reduced_fill_quantity(self):
        """Negative control for the branch: a FILLED row's fill_quantity IS
        its current tracked open size (already reduced by any partial exit),
        so it must stay on the other side of the branch."""
        from order_executor import _get_live_open_positions

        self._row("filled", quantity=10, fill_quantity=3)
        positions = _get_live_open_positions(include_unfilled=True)

        assert len(positions) == 1
        assert positions[0]["quantity"] == 3


class TestUnresolvableExitOrdersAreNeverParked:
    """Opus review (batch-58, H1). Parking an unresolvable EXIT row abandons
    settlement of the POSITION it closed. That position stays
    live=1/status='filled'/settled_at=NULL/closes_position_id=NULL -- exactly
    the shape get_filled_unsettled_live_orders() treats as open -- so the
    exit scanner would keep placing fresh REAL SELL orders for contracts the
    account no longer holds, every cycle, forever. The retry loop those
    branches exist for IS the protection, so it must survive the age cap."""

    def _position_and_exit(self, age_minutes):
        from datetime import UTC, datetime, timedelta

        import execution_log

        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        exit_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_exit"},
            closes_position_id=position_id,
        )
        placed = datetime.now(UTC) - timedelta(minutes=age_minutes)
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?",
                (placed.isoformat(), exit_id),
            )
        return position_id, exit_id

    def test_a_stale_unresolvable_exit_row_stays_in_the_retry_queue(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        _position_id, exit_id = self._position_and_exit(age_minutes=60 * 48)

        # uncertain=True: the lookup itself failed, so the row genuinely
        # stays 'unknown' rather than being confirmed not-found ('failed').
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(exit_id)["status"] == "unknown"
        assert execution_log.get_unresolved_live_orders() == []
        # It still escalates -- silence would be its own bug.
        assert mock_alert.called
        _title, message = mock_alert.call_args.args
        assert "coid_exit" in message

    def test_a_certain_unresolvable_exit_row_alerts_about_its_position(self):
        """The exit-specific escalation: the lookup DID execute and found
        the exit executed, but settlement of the position it closed keeps
        failing. That is the state where the exit scanner would otherwise
        keep firing real SELLs at an already-closed position, so the alert
        must name the orphaned position, not just the exit row."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        position_id, exit_id = self._position_and_exit(age_minutes=60 * 48)

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(
            # Real Kalshi enum value; there is no "filled" API status.
            {"order_id": "ord_exit", "status": "executed", "fill_count_fp": "10.00"},
            False,
        )
        with (
            patch("order_executor._settle_recovered_exit_order", return_value=False),
            patch("notify.send_system_alert") as mock_alert,
        ):
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(exit_id)["status"] == "unknown"
        assert execution_log.get_unresolved_live_orders() == []
        assert mock_alert.called
        title, message = mock_alert.call_args.args
        assert "exit" in title.lower()
        assert str(position_id) in message

    def test_a_stale_exit_row_is_still_re_polled_on_the_next_pass(self):
        """The whole point of not parking it: the retry must survive."""
        from unittest.mock import MagicMock, patch

        from order_executor import _recover_pending_orders

        self._position_and_exit(age_minutes=60 * 48)

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        with patch("notify.send_system_alert"):
            _recover_pending_orders(client)
            client._find_orders_by_client_ids.reset_mock()
            _recover_pending_orders(client)

        client._find_orders_by_client_ids.assert_called_once_with({"coid_exit"})

    def test_an_entry_row_of_the_same_age_is_still_parked(self):
        """Positive control for the branch: the exit carve-out must be about
        closes_position_id, not about the age cap having stopped working."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        entry_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=10,
            price=0.40,
            status="unknown",
            live=True,
            response={},  # no handle -> certain-and-unresolvable -> parks
        )
        placed = datetime.now(UTC) - timedelta(minutes=60 * 48)
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?",
                (placed.isoformat(), entry_id),
            )

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert"):
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(entry_id)["status"] == "unresolved"


class TestUnresolvedParkingRequiresACertainLookup:
    """Opus review (batch-58, L2): parking is terminal, so it must never be
    triggered by "we couldn't ask". One persistently-failing status bucket
    (e.g. _get_orders_by_status("canceled") raising on a reshaped payload for
    >24h) sets the PASS-level uncertain flag for every row -- without this
    guard, every live 'unknown' row would be abandoned at the age mark even
    though the resting/executed walks were healthy."""

    def _stale_unknown(self, cid="coid_x"):  # cid=None -> no usable handle
        from datetime import UTC, datetime, timedelta

        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="unknown",
            live=True,
            response=({"client_order_id": cid} if cid else {}),
        )
        placed = datetime.now(UTC) - timedelta(minutes=60 * 48)
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?",
                (placed.isoformat(), row_id),
            )
        return row_id

    def test_an_uncertain_pass_does_not_park(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._stale_unknown()
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, True)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unknown"
        assert execution_log.get_unresolved_live_orders() == []
        # It still ESCALATES -- a >24h broken lookup is its own incident.
        # Only the terminal park is withheld.
        assert mock_alert.called
        assert "lookup failing" in mock_alert.call_args.args[0].lower()

    def test_a_certain_pass_of_the_same_age_does_park(self):
        """Positive control: identical age, lookup NOT failing, and the row
        is genuinely unresolvable (no stored client_order_id, so there is no
        handle to re-check by and waiting longer cannot change the answer).
        This is the case parking exists for."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = self._stale_unknown(cid=None)
        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert"):
            _recover_pending_orders(client)

        assert execution_log.get_order_by_id(row_id)["status"] == "unresolved"


class TestUnresolvedAlertCooldownIsPerRow:
    """Opus review (batch-58, M1): notify.send_system_alert applies a 6-hour
    disk-persisted cooldown keyed on cooldown_key. A single shared key meant
    that when an outage parked four rows in one pass, exactly ONE alert was
    delivered and the other three parked silently -- each of which may be a
    real resting order."""

    def test_each_parked_row_gets_its_own_cooldown_key(self):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _recover_pending_orders

        row_ids = []
        for i in range(3):
            row_id = execution_log.log_order(
                ticker=f"KXHIGH-25MAY15-T{75 + i}",
                side="yes",
                quantity=10,
                price=0.40,
                status="unknown",
                live=True,
                response={},  # no handle -> certain-and-unresolvable -> parks
            )
            placed = datetime.now(UTC) - timedelta(minutes=60 * 48)
            with execution_log._conn() as con:
                con.execute(
                    "UPDATE orders SET placed_at = ? WHERE id = ?",
                    (placed.isoformat(), row_id),
                )
            row_ids.append(row_id)

        client = MagicMock()
        client._find_orders_by_client_ids.side_effect = _batched_lookup(None, False)
        with patch("notify.send_system_alert") as mock_alert:
            _recover_pending_orders(client)

        keys = {c.kwargs["cooldown_key"] for c in mock_alert.call_args_list}
        assert keys == {f"unresolved_live_order:{r}" for r in row_ids}
        assert len(keys) == 3, "a shared key would collapse these to one"


class TestExitBlockedAlertScope:
    """Opus review (batch-58, L6): LIVE_TRADING_ENABLED unset is a legitimate
    steady state -- an operator disarming while holding positions is how this
    bot sits today. Alerting on it would re-nag every 6h forever for a state
    the operator chose. The two ACTIONS (kill switch, TRADING_PAUSED) are the
    ones worth interrupting someone over."""

    def _position(self):
        return {
            "id": 1,
            "ticker": "KXHIGH-25MAY15-T75",
            "side": "yes",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "close_time": "2026-05-16T12:00:00+00:00",
        }

    def test_an_operator_action_alerts(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _exit_live_position

        for reason in (
            "Kill switch active (data/.kill_switch)",
            "TRADING_PAUSED is set",
        ):
            with (
                patch(
                    "trading_gates.pre_live_exit_check",
                    side_effect=RuntimeError(reason),
                ),
                patch("notify.send_system_alert") as mock_alert,
            ):
                _exit_live_position(
                    MagicMock(), self._position(), 0.20, "stop_loss", "2026-05-15_12z"
                )
            assert mock_alert.called, f"{reason} should alert"

    def test_a_disarmed_configuration_does_not_alert(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _exit_live_position

        for reason in (
            "LIVE_TRADING_ENABLED not set to 'true'",
            "client not pointed at prod (base_url=https://demo-api.kalshi.co/trade-api/v2)",
        ):
            with (
                patch(
                    "trading_gates.pre_live_exit_check",
                    side_effect=RuntimeError(reason),
                ),
                patch("notify.send_system_alert") as mock_alert,
            ):
                result = _exit_live_position(
                    MagicMock(), self._position(), 0.20, "stop_loss", "2026-05-15_12z"
                )
            # Still blocked, still returns False -- only the ALERT is scoped.
            assert result is False
            mock_alert.assert_not_called(), f"{reason} should not re-nag"
