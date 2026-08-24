"""Tests for batch-40 "Between-bracket calibration design", Decision 2
(shadow-only until validated): the real-money-exposure enforcement points
for weather_markets._between_metar_gates_active() /
weather_markets.is_between_bracket_ticker() outside weather_markets.py
itself -- order_executor._auto_place_trades' shadow routing,
paper.check_position_limits' shared backstop, and main.py's three manual
placement paths (cmd_order, _quick_paper_buy, cmd_paper). Mirrors the
existing rain/snow/hourly/storm-order tests for the same enforcement
points (tests/test_shadow_predictions.py, tests/test_rain_markets.py,
tests/test_hurricane_gating.py) but is kept in its own new file per this
batch's test-scoping instructions (order_executor.py/paper.py/main.py are
not in the two pre-existing scoped test files)."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import order_executor
import tracker


def _make_between_opp(ticker="KXHIGHNY-26AUG24-B67.5", city="NYC", net_edge=0.30):
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "side": "yes",
        "_city": city,
        "_date": datetime.date.today(),
        "ci_adjusted_kelly": 0.15,
        "fee_adjusted_kelly": 0.15,
        "market_prob": 0.50,
        "forecast_prob": 0.80,
        "net_edge": net_edge,
        "model_consensus": True,
        "method": "metar_lockout",
        "condition": {"type": "between", "lower": 66.5, "upper": 68.5},
        "metar_locked": True,
    }


def _fetch(ticker):
    with tracker._conn() as con:
        return con.execute(
            "SELECT ticker, city, method, our_prob, market_prob, is_shadow "
            "FROM predictions WHERE ticker=?",
            (ticker,),
        ).fetchall()


def _place_everything_setup(monkeypatch):
    """Mirrors test_shadow_predictions.py's own helper of the same name."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)
    monkeypatch.setattr("paper.is_paused_drawdown", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr(
        "paper.kelly_quantity",
        lambda kf, p, cap=None, method=None, client=None, **_kw: 5,
    )
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None, client=None: kf
    )
    monkeypatch.setattr("order_executor._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("order_executor._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_this_cycle", lambda t, s, c: False
    )


class TestAutoPlaceTradesShadowRoutesBetween:
    def test_between_ticker_shadow_only_when_gate_inactive(self, monkeypatch):
        _place_everything_setup(monkeypatch)
        monkeypatch.setattr("order_executor._between_metar_gates_active", lambda: False)
        placed_calls = []
        monkeypatch.setattr(
            "order_executor.place_paper_order",
            lambda *a, **k: placed_calls.append((a, k))
            or {"id": 1, "status": "open", "cost": 1.0},
        )
        opp = _make_between_opp("KXHIGHNY-26AUG24-B67.5")

        result = order_executor._auto_place_trades([opp], client=None)

        assert result == 0
        assert placed_calls == [], (
            "must never place a real order for a gated between ticker"
        )
        rows = _fetch("KXHIGHNY-26AUG24-B67.5")
        assert len(rows) == 1
        assert rows[0]["is_shadow"] == 1

    def test_between_ticker_places_normally_when_gate_active(self, monkeypatch):
        """Once _between_metar_gates_active() is True, a between opp places
        exactly like any other ticker -- no special-casing beyond the gate
        check."""
        _place_everything_setup(monkeypatch)
        monkeypatch.setattr("order_executor._between_metar_gates_active", lambda: True)
        monkeypatch.setattr(
            "order_executor.place_paper_order",
            lambda ticker, side, qty, price, **kwargs: {
                "id": 1,
                "status": "open",
                "cost": price * qty,
            },
        )
        opp = _make_between_opp("KXHIGHNY-26AUG24-B67.5")

        order_executor._auto_place_trades([opp], client=None)

        rows = _fetch("KXHIGHNY-26AUG24-B67.5")
        assert len(rows) == 1
        assert rows[0]["is_shadow"] == 0

    def test_mixed_batch_between_shadow_daily_places_normally(self, monkeypatch):
        """The core routing guarantee: in one batch, a between opp (gate
        inactive) is shadow-logged while an above/below opp in the SAME
        batch places normally -- above/below is entirely unaffected by
        this gate."""
        _place_everything_setup(monkeypatch)
        monkeypatch.setattr("order_executor._between_metar_gates_active", lambda: False)
        placed_calls = []
        monkeypatch.setattr(
            "order_executor.place_paper_order",
            lambda ticker, side, qty, price, **kwargs: (
                placed_calls.append(ticker),
                {"id": 1, "status": "open", "cost": price * qty},
            )[1],
        )
        between_opp = _make_between_opp("KXHIGHNY-26AUG24-B67.5")
        daily_opp = {
            **_make_between_opp("KXHIGHNY-26AUG24-T70"),
            "method": "ensemble",
            "condition": {"type": "above", "threshold": 70.0},
            "metar_locked": False,
        }

        order_executor._auto_place_trades([between_opp, daily_opp], client=None)

        assert placed_calls == ["KXHIGHNY-26AUG24-T70"], (
            "only the daily above/below ticker should have gone through "
            "place_paper_order"
        )
        between_rows = _fetch("KXHIGHNY-26AUG24-B67.5")
        assert len(between_rows) == 1 and between_rows[0]["is_shadow"] == 1
        daily_rows = _fetch("KXHIGHNY-26AUG24-T70")
        assert len(daily_rows) == 1 and daily_rows[0]["is_shadow"] == 0


class TestCheckPositionLimitsBetweenConditional:
    """Mirrors test_rain_markets.py's TestCheckPositionLimitsRainConditional
    exactly -- paper.check_position_limits() is the shared enforcement
    point cmd_order/cmd_paper/web_app's /api/paper-order all route
    through."""

    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits(
            "KXHIGHNY-26AUG24-B67.5", qty=1, price=0.10
        )
        assert result["ok"] is False
        assert "between" in result["reason"].lower()

    def test_does_not_block_when_gate_active(self, monkeypatch):
        """Mutation-test proof: flipping _between_metar_gates_active() to
        True makes the block disappear -- confirms the conditional is real."""
        import paper

        monkeypatch.setattr("weather_markets._between_metar_gates_active", lambda: True)
        result = paper.check_position_limits(
            "KXHIGHNY-26AUG24-B67.5", qty=1, price=0.10
        )
        assert result["ok"] is True

    def test_above_below_ticker_unaffected(self, monkeypatch):
        """Regression control: an ordinary above/below ticker must reach
        the real exposure-cap logic (not the new between guard) -- this
        gate's default-off posture must not accidentally block above/below
        trades on the same KXHIGH*/KXLOW* series."""
        from unittest.mock import patch

        import paper

        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)
        with patch("paper.get_open_trades", return_value=[]):
            with patch("paper.get_total_exposure", return_value=0.0):
                result = paper.check_position_limits(
                    "KXHIGHNY-26AUG24-T70", qty=1, price=0.50
                )
        assert result["ok"] is True


class TestManualPlacementPathsRefuseBetweenWhenGateInactive:
    """main.py's 3 manual placement paths -- cmd_order, _quick_paper_buy,
    cmd_paper -- each carry an explicit refuse-outright guard, same
    fail-closed-even-if-check_position_limits-raises reasoning as every
    other shadow family's own guard."""

    def test_cmd_order_refuses_without_fetching_market_or_placing_order(
        self, monkeypatch, capsys
    ):
        import main

        mock_client = MagicMock()
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)

        main.cmd_order(
            mock_client, "buy", ["KXHIGHNY-26AUG24-B67.5", "yes", "5", "0.50"]
        )

        mock_client.get_market.assert_not_called()
        mock_client.place_order.assert_not_called()
        out = capsys.readouterr().out
        assert "between" in out.lower()
        assert "BETWEEN_TRADING_ENABLED" in out

    def test_cmd_order_daily_ticker_unaffected(self, monkeypatch):
        """Regression control: an above/below ticker must reach past this
        guard (it still needs a real Kalshi client to place, so this only
        confirms the between-specific refusal doesn't fire)."""
        import main

        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)

        try:
            main.cmd_order(
                mock_client, "buy", ["KXHIGHNY-26AUG24-T70", "yes", "5", "0.50"]
            )
        except Exception:
            pass
        mock_client.get_market.assert_called()

    def test_quick_paper_buy_refuses_between_when_gate_inactive(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXHIGHNY-26AUG24-B67.5"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "between" in out.lower()
        assert "BETWEEN_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()

    def test_quick_paper_buy_does_not_refuse_between_when_gate_active(
        self, monkeypatch
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._between_metar_gates_active", lambda: True)
        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        _inputs = iter(["KXHIGHNY-26AUG24-B67.5", "q"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main._quick_paper_buy(mock_client)
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)

    def test_cmd_paper_refuses_between_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("BETWEEN_TRADING_ENABLED", raising=False)

        main.cmd_paper(["buy", "KXHIGHNY-26AUG24-B67.5", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "between" in out.lower()
        assert "BETWEEN_TRADING_ENABLED" in out

    def test_cmd_paper_does_not_refuse_between_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._between_metar_gates_active", lambda: True)

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_paper(["buy", "KXHIGHNY-26AUG24-B67.5", "yes", "0.10", "1"])
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)
