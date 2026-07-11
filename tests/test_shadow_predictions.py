"""Tests for _log_shadow_predictions: when a trade would have been placed but
wasn't (TRADING_PAUSED, drawdown halt, daily-loss halt, or a whole-batch
position/spend cap), _auto_place_trades should still log a prediction for
each opp that reached that guard, so brier_score_by_method() (and strategy
auto-retirement) keeps reflecting current forecast quality instead of
freezing. Shadow logging must apply the same validation/dedup gates the real
placement loop uses, and must flag rows with is_shadow=1 so downstream
P&L-labeled consumers can tell them apart from a trade-backed prediction."""

import datetime

import order_executor
import tracker


def _make_flat_opp(ticker="KXSHADOW", city="NYC", net_edge=0.30):
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "side": "yes",
        "_city": city,
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": 0.15,
        "fee_adjusted_kelly": 0.15,
        "market_prob": 0.50,
        "forecast_prob": 0.80,
        "net_edge": net_edge,
        "model_consensus": True,
        "method": "ensemble",
        "condition": {"type": "above", "threshold": 82.0},
    }


def _fetch(ticker):
    with tracker._conn() as con:
        return con.execute(
            "SELECT ticker, city, method, our_prob, market_prob, is_shadow "
            "FROM predictions WHERE ticker=?",
            (ticker,),
        ).fetchall()


def test_trading_paused_logs_shadow_prediction(monkeypatch):
    monkeypatch.setenv("TRADING_PAUSED", "true")
    opp = _make_flat_opp("KXSHADOWFLAT")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    rows = _fetch("KXSHADOWFLAT")
    assert len(rows) == 1
    row = rows[0]
    assert row["city"] == "NYC"
    assert row["method"] == "ensemble"
    assert row["our_prob"] == 0.80
    assert row["market_prob"] == 0.50
    assert row["is_shadow"] == 1


def test_trading_paused_logs_shadow_prediction_tuple_format(monkeypatch):
    monkeypatch.setenv("TRADING_PAUSED", "true")
    market = {
        "ticker": "KXSHADOWTUP",
        "_city": "CHI",
        "_date": datetime.date.today() + datetime.timedelta(days=2),
    }
    analysis = {
        "recommended_side": "yes",
        "market_prob": 0.40,
        "forecast_prob": 0.65,
        "net_edge": 0.25,
        "ci_adjusted_kelly": 0.10,
        "method": "normal_dist",
        "condition": {"type": "above", "threshold": 90.0},
    }

    result = order_executor._auto_place_trades([(market, analysis)], client=None)

    assert result == 0
    rows = _fetch("KXSHADOWTUP")
    assert len(rows) == 1
    row = rows[0]
    assert row["city"] == "CHI"
    assert row["method"] == "normal_dist"
    assert row["our_prob"] == 0.65
    assert row["market_prob"] == 0.40
    assert row["is_shadow"] == 1


def test_trading_paused_does_not_place_trade(monkeypatch):
    """Shadow logging must never place an actual order — only observe."""
    monkeypatch.setenv("TRADING_PAUSED", "true")
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k)),
    )
    opp = _make_flat_opp("KXSHADOWNOTRADE")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == []


def test_trading_paused_skips_invalid_opp(monkeypatch):
    """A signal that _validate_trade_opportunity would reject (here: non-positive
    edge) must not get shadow-logged — otherwise garbage data pollutes the same
    Brier-scoring table auto-retirement reads."""
    monkeypatch.setenv("TRADING_PAUSED", "true")
    bad_opp = _make_flat_opp("KXSHADOWBADEDGE", net_edge=-0.10)

    result = order_executor._auto_place_trades([bad_opp], client=None)

    assert result == 0
    assert _fetch("KXSHADOWBADEDGE") == []


def test_trading_paused_skips_already_open_ticker(monkeypatch):
    """A ticker with an existing open position must not get re-logged every
    cron cycle it remains held — that would overweight it in Brier scoring
    relative to a signal that only ever fires once."""
    monkeypatch.setenv("TRADING_PAUSED", "true")
    monkeypatch.setattr(
        "paper.get_open_trades",
        lambda: [{"ticker": "KXSHADOWHELD", "side": "yes"}],
    )
    opp = _make_flat_opp("KXSHADOWHELD")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert _fetch("KXSHADOWHELD") == []


def test_trading_paused_logs_multiple_opps_in_one_batch(monkeypatch):
    """Multiple opps in one call share a single batched DB connection —
    confirm both still land as separate rows."""
    monkeypatch.setenv("TRADING_PAUSED", "true")
    opps = [_make_flat_opp("KXSHADOWBATCH1"), _make_flat_opp("KXSHADOWBATCH2")]

    result = order_executor._auto_place_trades(opps, client=None)

    assert result == 0
    assert len(_fetch("KXSHADOWBATCH1")) == 1
    assert len(_fetch("KXSHADOWBATCH2")) == 1


def test_drawdown_halt_also_logs_shadow_prediction(monkeypatch):
    """Drawdown halt causes the identical 'no trade placed' staleness problem
    as TRADING_PAUSED — it should shadow-log too, not just the pause branch."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: True)
    opp = _make_flat_opp("KXSHADOWDRAWDOWN")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    rows = _fetch("KXSHADOWDRAWDOWN")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_real_placement_logs_is_shadow_false(monkeypatch):
    """Sanity check for the is_shadow column itself: a real, successfully
    placed trade must be flagged is_shadow=0, not just absent/NULL."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)
    # _make_flat_opp's opp has no days_out key (defaults to 1, multi-day),
    # which the real, wall-clock-dependent _in_gfs_update_window() gates --
    # not mocking this makes the test spuriously fail whenever it runs
    # during that recurring UTC window.
    monkeypatch.setattr(
        "order_executor._in_gfs_update_window", lambda now_utc=None: False
    )
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr("paper.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf
    )
    monkeypatch.setattr("order_executor._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("order_executor._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_this_cycle", lambda t, s, c: False
    )
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXREALPLACED")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXREALPLACED")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0
