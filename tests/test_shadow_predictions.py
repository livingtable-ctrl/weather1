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
    monkeypatch.setattr("paper.is_paused_drawdown", lambda *_a, **_k: True)
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
    monkeypatch.setattr("paper.is_paused_drawdown", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr(
        "paper.kelly_quantity", lambda kf, p, cap=None, method=None, client=None: 5
    )
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None, client=None: kf
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


# ── backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item
# 5: hourly markets stay shadow-only independent of TRADING_PAUSED, per-
# ticker rather than per-batch, until _hourly_gates_active() fires. ─────────


def _place_everything_setup(monkeypatch):
    """Mirrors test_real_placement_logs_is_shadow_false's full mock setup so
    a real placement can reach the finish line for any opp that clears the
    hourly gate check."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)
    monkeypatch.setattr("paper.is_paused_drawdown", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda *_a, **_k: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr(
        "paper.kelly_quantity", lambda kf, p, cap=None, method=None, client=None: 5
    )
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None, client=None: kf
    )
    monkeypatch.setattr("order_executor._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("order_executor._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_this_cycle", lambda t, s, c: False
    )


def test_hourly_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """An hourly (KXTEMPxxxH) opp must be shadow-logged, not placed, when
    _hourly_gates_active() is False -- independent of TRADING_PAUSED (which
    is explicitly cleared here)."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXTEMPNYCH-26JUL2014-T75.99")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], "must never place a real order for a gated hourly ticker"
    rows = _fetch("KXTEMPNYCH-26JUL2014-T75.99")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_hourly_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _hourly_gates_active() is True, an hourly opp places exactly
    like any other ticker -- no special-casing beyond the gate check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXTEMPNYCH-26JUL2015-T75.99")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXTEMPNYCH-26JUL2015-T75.99")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_mixed_batch_hourly_shadow_daily_places_normally(monkeypatch):
    """The core routing guarantee: in one batch, an hourly opp (gate
    inactive) is shadow-logged while a daily opp in the SAME batch places
    normally -- confirms the new per-ticker branch doesn't regress the
    existing whole-batch behavior for non-hourly opportunities."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: (
            placed_calls.append(ticker),
            {"id": 1, "status": "open", "cost": price * qty},
        )[1],
    )
    hourly_opp = _make_flat_opp("KXTEMPNYCH-26JUL2016-T75.99")
    daily_opp = _make_flat_opp("KXHIGHNY-26JUL20-T80")

    order_executor._auto_place_trades([hourly_opp, daily_opp], client=None)

    assert placed_calls == ["KXHIGHNY-26JUL20-T80"], (
        "only the daily ticker should have gone through place_paper_order"
    )
    hourly_rows = _fetch("KXTEMPNYCH-26JUL2016-T75.99")
    assert len(hourly_rows) == 1 and hourly_rows[0]["is_shadow"] == 1
    daily_rows = _fetch("KXHIGHNY-26JUL20-T80")
    assert len(daily_rows) == 1 and daily_rows[0]["is_shadow"] == 0


# ── backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 7:
# monthly-rain markets stay shadow-only independent of TRADING_PAUSED,
# per-ticker rather than per-batch, until _rain_gates_active() fires. Same
# shape as the hourly tests above. ──────────────────────────────────────────


def test_rain_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """A monthly-rain (KXRAIN*M) opp must be shadow-logged, not placed, when
    _rain_gates_active() is False -- independent of TRADING_PAUSED (which is
    explicitly cleared here)."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._rain_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXRAINDENM-26JUL-7", city="Denver")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], "must never place a real order for a gated rain ticker"
    rows = _fetch("KXRAINDENM-26JUL-7")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_rain_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _rain_gates_active() is True, a rain opp places exactly like
    any other ticker -- no special-casing beyond the gate check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._rain_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXRAINDENM-26AUG-7", city="Denver")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXRAINDENM-26AUG-7")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_mixed_batch_rain_shadow_daily_places_normally(monkeypatch):
    """The core routing guarantee: in one batch, a rain opp (gate inactive)
    is shadow-logged while a daily opp in the SAME batch places normally."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._rain_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: (
            placed_calls.append(ticker),
            {"id": 1, "status": "open", "cost": price * qty},
        )[1],
    )
    rain_opp = _make_flat_opp("KXRAINSEAM-26SEP-1", city="Seattle")
    daily_opp = _make_flat_opp("KXHIGHNY-26JUL21-T80")

    order_executor._auto_place_trades([rain_opp, daily_opp], client=None)

    assert placed_calls == ["KXHIGHNY-26JUL21-T80"], (
        "only the daily ticker should have gone through place_paper_order"
    )
    rain_rows = _fetch("KXRAINSEAM-26SEP-1")
    assert len(rain_rows) == 1 and rain_rows[0]["is_shadow"] == 1
    daily_rows = _fetch("KXHIGHNY-26JUL21-T80")
    assert len(daily_rows) == 1 and daily_rows[0]["is_shadow"] == 0


# ── backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Snow Step 2: monthly-snow
# markets stay shadow-only independent of TRADING_PAUSED, per-ticker rather
# than per-batch, until _snow_gates_active() fires. Mirrors the rain tests
# above exactly. ─────────────────────────────────────────────────────────────


def test_snow_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """A monthly-snow (KXDENSNOWM) opp must be shadow-logged, not placed,
    when _snow_gates_active() is False -- independent of TRADING_PAUSED
    (which is explicitly cleared here)."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._snow_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXDENSNOWM-26DEC-5", city="Denver")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], "must never place a real order for a gated snow ticker"
    rows = _fetch("KXDENSNOWM-26DEC-5")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_snow_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _snow_gates_active() is True, a snow opp places exactly like
    any other ticker -- no special-casing beyond the gate check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._snow_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXDENSNOWM-26DEC-10", city="Denver")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXDENSNOWM-26DEC-10")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_mixed_batch_snow_shadow_daily_places_normally(monkeypatch):
    """The core routing guarantee: in one batch, a snow opp (gate inactive)
    is shadow-logged while a daily opp in the SAME batch places normally."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._snow_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: (
            placed_calls.append(ticker),
            {"id": 1, "status": "open", "cost": price * qty},
        )[1],
    )
    snow_opp = _make_flat_opp("KXDENSNOWM-26DEC-15", city="Denver")
    daily_opp = _make_flat_opp("KXHIGHNY-26JUL22-T80")

    order_executor._auto_place_trades([snow_opp, daily_opp], client=None)

    assert placed_calls == ["KXHIGHNY-26JUL22-T80"], (
        "only the daily ticker should have gone through place_paper_order"
    )
    snow_rows = _fetch("KXDENSNOWM-26DEC-15")
    assert len(snow_rows) == 1 and snow_rows[0]["is_shadow"] == 1
    daily_rows = _fetch("KXHIGHNY-26JUL22-T80")
    assert len(daily_rows) == 1 and daily_rows[0]["is_shadow"] == 0


# ── backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03):
# the 5 season-total hurricane/tropical-storm-count series stay shadow-only
# independent of TRADING_PAUSED, per-ticker rather than per-batch, until
# _hurricane_count_gates_active() fires. Mirrors the rain/snow tests above
# exactly. City is a synthetic "HUR_<basin>" key (no real city for this
# market family), matching _analyze_hurricane_count_trade's own exposure-cap
# grouping design. ───────────────────────────────────────────────────────────


def test_hurricane_count_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """A hurricane season-count (KXHURCTOT) opp must be shadow-logged, not
    placed, when _hurricane_count_gates_active() is False -- independent of
    TRADING_PAUSED (which is explicitly cleared here)."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hurricane_count_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXHURCTOT-26DEC01-T7", city="HUR_ATL")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], (
        "must never place a real order for a gated hurricane-count ticker"
    )
    rows = _fetch("KXHURCTOT-26DEC01-T7")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_hurricane_count_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _hurricane_count_gates_active() is True, a hurricane-count opp
    places exactly like any other ticker -- no special-casing beyond the
    gate check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hurricane_count_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXHURCTOT-26DEC01-T9", city="HUR_ATL")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXHURCTOT-26DEC01-T9")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_mixed_batch_hurricane_count_shadow_daily_places_normally(monkeypatch):
    """The core routing guarantee: in one batch, a hurricane-count opp (gate
    inactive) is shadow-logged while a daily opp in the SAME batch places
    normally."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hurricane_count_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: (
            placed_calls.append(ticker),
            {"id": 1, "status": "open", "cost": price * qty},
        )[1],
    )
    hurricane_opp = _make_flat_opp("KXTROPSTORM-26DEC01-T14", city="HUR_ATL")
    daily_opp = _make_flat_opp("KXHIGHNY-26JUL23-T80")

    order_executor._auto_place_trades([hurricane_opp, daily_opp], client=None)

    assert placed_calls == ["KXHIGHNY-26JUL23-T80"], (
        "only the daily ticker should have gone through place_paper_order"
    )
    hurricane_rows = _fetch("KXTROPSTORM-26DEC01-T14")
    assert len(hurricane_rows) == 1 and hurricane_rows[0]["is_shadow"] == 1
    daily_rows = _fetch("KXHIGHNY-26JUL23-T80")
    assert len(daily_rows) == 1 and daily_rows[0]["is_shadow"] == 0


def test_hurricane_count_gate_evaluated_once_per_batch(monkeypatch):
    """Regression test: each shadow-only gate must be evaluated ONCE per
    _auto_place_trades() call, not once per ticker in the batch. Each real
    gate sits behind a live settled-sample DB count, so per-ticker
    recomputation risked two tickers of the SAME family observing different
    gate values within a single call if the underlying count changed
    mid-batch (e.g. a concurrent settle write). Asserts on CALL COUNT, not
    just on outcome, so it fails against a per-ticker call pattern even when
    the mocked gate always returns the same value."""
    _place_everything_setup(monkeypatch)
    call_count = {"n": 0}

    def _counting_gate():
        call_count["n"] += 1
        return False

    monkeypatch.setattr("order_executor._hurricane_count_gates_active", _counting_gate)
    opp1 = _make_flat_opp("KXTROPSTORM-26DEC01-T15", city="HUR_ATL")
    opp2 = _make_flat_opp("KXTROPSTORM-26DEC01-T16", city="HUR_ATL")
    opp3 = _make_flat_opp("KXHURCTOT-26DEC01-T3", city="HUR_ATL")

    order_executor._auto_place_trades([opp1, opp2, opp3], client=None)

    assert call_count["n"] == 1, (
        f"expected the hurricane-count gate to be evaluated exactly once "
        f"per batch, got {call_count['n']} call(s)"
    )


def test_hurricane_count_gate_stable_within_batch_despite_stateful_mock(monkeypatch):
    """If the gate's underlying value changed mid-batch (settled count
    crossing the sample floor between two tickers of the same family), the
    once-per-batch hoist guarantees every ticker in the batch still observes
    the value taken at the START of the batch. Reproduces the exact
    stateful-flip shape a naive per-ticker call is NOT immune to: with the
    stub below, a per-ticker call pattern would shadow-gate the first
    ticker but place the second for real."""
    _place_everything_setup(monkeypatch)
    responses = iter([False, True, True])
    monkeypatch.setattr(
        "order_executor._hurricane_count_gates_active", lambda: next(responses)
    )
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: (
            placed_calls.append(ticker),
            {"id": 1, "status": "open", "cost": price * qty},
        )[1],
    )
    opp1 = _make_flat_opp("KXTROPSTORM-26DEC01-T17", city="HUR_ATL")
    opp2 = _make_flat_opp("KXTROPSTORM-26DEC01-T18", city="HUR_ATL")

    order_executor._auto_place_trades([opp1, opp2], client=None)

    assert placed_calls == [], (
        "both hurricane-count tickers must be shadow-gated together -- the "
        "gate value must not flip mid-batch even though the underlying "
        "stub would return a different value on a later call"
    )
    rows1 = _fetch("KXTROPSTORM-26DEC01-T17")
    rows2 = _fetch("KXTROPSTORM-26DEC01-T18")
    assert rows1[0]["is_shadow"] == 1
    assert rows2[0]["is_shadow"] == 1


# ── backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
# (2026-08-07): KXNEXTHURDATE/KXNEXTCAT5HURDATE stay shadow-only,
# independent of the count model's own gate, until
# _hurricane_next_event_gates_active() fires. Mirrors the hurricane-count
# tests above exactly. ────────────────────────────────────────────────────


def test_hurricane_next_event_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """A time-to-next-event (KXNEXTHURDATE) opp must be shadow-logged, not
    placed, when _hurricane_next_event_gates_active() is False."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr(
        "order_executor._hurricane_next_event_gates_active", lambda: False
    )
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXNEXTHURDATE-26DEC01-26SEP15", city="HUR_ATL")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], (
        "must never place a real order for a gated hurricane-next-event ticker"
    )
    rows = _fetch("KXNEXTHURDATE-26DEC01-26SEP15")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_hurricane_next_event_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _hurricane_next_event_gates_active() is True, a next-event opp
    places exactly like any other ticker -- no special-casing beyond the
    gate check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr(
        "order_executor._hurricane_next_event_gates_active", lambda: True
    )
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXNEXTCAT5HURDATE-26DEC01-26SEP01", city="HUR_ATL")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXNEXTCAT5HURDATE-26DEC01-26SEP01")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_hurricane_count_gate_state_does_not_affect_next_event_routing(monkeypatch):
    """The two hurricane sub-models' gates are independent -- the count
    model's gate being active must NOT let a next-event opp place, and vice
    versa (confirmed here for the count-active/next-event-inactive
    direction; the reverse is already implicit in the two tests above)."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hurricane_count_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor._hurricane_next_event_gates_active", lambda: False
    )
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXNEXTHURDATE-26DEC01-26OCT01", city="HUR_ATL")

    order_executor._auto_place_trades([opp], client=None)

    assert placed_calls == []
    rows = _fetch("KXNEXTHURDATE-26DEC01-26OCT01")
    assert len(rows) == 1 and rows[0]["is_shadow"] == 1


# ── backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07):
# KXFIRSTHURRICANE stays shadow-only, independent of both sibling models'
# own gates, until _storm_order_gates_active() fires. Mirrors the
# hurricane-next-event tests above exactly. ─────────────────────────────────


def test_storm_order_ticker_shadow_only_when_gate_inactive(monkeypatch):
    """A storm-order (KXFIRSTHURRICANE) opp must be shadow-logged, not
    placed, when _storm_order_gates_active() is False."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._storm_order_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXFIRSTHURRICANE-26DEC01ATL-ART", city="HUR_ATL")

    result = order_executor._auto_place_trades([opp], client=None)

    assert result == 0
    assert placed_calls == [], (
        "must never place a real order for a gated storm-order ticker"
    )
    rows = _fetch("KXFIRSTHURRICANE-26DEC01ATL-ART")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 1


def test_storm_order_ticker_places_normally_when_gate_active(monkeypatch):
    """Once _storm_order_gates_active() is True, a storm-order opp places
    exactly like any other ticker -- no special-casing beyond the gate
    check."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._storm_order_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: {
            "id": 1,
            "status": "open",
            "cost": price * qty,
        },
    )
    opp = _make_flat_opp("KXFIRSTHURRICANE-26DEC01ATL-WIL", city="HUR_ATL")

    order_executor._auto_place_trades([opp], client=None)

    rows = _fetch("KXFIRSTHURRICANE-26DEC01ATL-WIL")
    assert len(rows) == 1
    assert rows[0]["is_shadow"] == 0


def test_sibling_hurricane_gate_state_does_not_affect_storm_order_routing(monkeypatch):
    """All 3 hurricane sub-models' gates are independent -- a sibling
    model's gate being active must NOT let a storm-order opp place, and
    vice versa."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hurricane_count_gates_active", lambda: True)
    monkeypatch.setattr(
        "order_executor._hurricane_next_event_gates_active", lambda: True
    )
    monkeypatch.setattr("order_executor._storm_order_gates_active", lambda: False)
    placed_calls = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda *a, **k: placed_calls.append((a, k))
        or {"id": 1, "status": "open", "cost": 1.0},
    )
    opp = _make_flat_opp("KXFIRSTHURRICANE-26DEC01ATL-JOS", city="HUR_ATL")

    order_executor._auto_place_trades([opp], client=None)

    assert placed_calls == []
    rows = _fetch("KXFIRSTHURRICANE-26DEC01ATL-JOS")
    assert len(rows) == 1 and rows[0]["is_shadow"] == 1


# ── AUD-0021: shadow logging must batch across the WHOLE per-ticker loop,
# not call _log_shadow_predictions once per shadow-routed ticker -- each
# call independently reopens a tracker connection and re-reads the paper
# ledger with no caching, so N shadow-routed tickers meant N connection
# opens instead of 1. ──────────────────────────────────────────────────


def test_shadow_routed_tickers_across_different_families_batch_into_one_call(
    monkeypatch,
):
    """Two shadow-routed opps from DIFFERENT families (hourly + rain) in the
    same batch must trigger exactly ONE _log_shadow_predictions call, not
    one per ticker -- the actual N+1 pattern AUD-0021 describes."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: False)
    monkeypatch.setattr("order_executor._rain_gates_active", lambda: False)

    real_fn = order_executor._log_shadow_predictions
    calls = []

    def _counting_wrapper(opps, live=False):
        calls.append(list(opps))
        return real_fn(opps, live=live)

    monkeypatch.setattr("order_executor._log_shadow_predictions", _counting_wrapper)

    hourly_opp = _make_flat_opp("KXTEMPNYCH-26JUL2017-T75.99")
    rain_opp = _make_flat_opp("KXRAINDENM-26OCT-7", city="Denver")

    order_executor._auto_place_trades([hourly_opp, rain_opp], client=None)

    assert len(calls) == 1, (
        f"expected exactly 1 batched _log_shadow_predictions call, got {len(calls)}"
    )
    assert len(calls[0]) == 2, "the single call must carry BOTH shadow-routed opps"

    hourly_rows = _fetch("KXTEMPNYCH-26JUL2017-T75.99")
    assert len(hourly_rows) == 1 and hourly_rows[0]["is_shadow"] == 1
    rain_rows = _fetch("KXRAINDENM-26OCT-7")
    assert len(rain_rows) == 1 and rain_rows[0]["is_shadow"] == 1


def test_shadow_batch_skip_reasons_report_per_ticker_logged_status(monkeypatch):
    """The console diagnostic (_skip_reasons) must still report each
    shadow-routed ticker's OWN logged=True/False outcome after batching --
    not just an aggregate count -- so a per-ticker validation/dedup failure
    inside the batched call stays individually visible."""
    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: False)
    # This ticker will fail _log_shadow_predictions' own internal
    # was_ordered_recently gate, so it's shadow-ROUTED but not shadow-
    # LOGGED -- the batch must still tell the two tickers apart.
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_recently",
        lambda ticker, days=7: ticker == "KXTEMPNYCH-26JUL2018-T75.99",
    )

    logs_ok = _make_flat_opp("KXTEMPNYCH-26JUL2019-T75.99")
    fails_dedup = _make_flat_opp("KXTEMPNYCH-26JUL2018-T75.99")

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        order_executor._auto_place_trades([logs_ok, fails_dedup], client=None)
    out = buf.getvalue()

    assert "KXTEMPNYCH-26JUL2019-T75.99: hourly_shadow_only(logged=True)" in out
    assert "KXTEMPNYCH-26JUL2018-T75.99: hourly_shadow_only(logged=False)" in out


def test_kwargs_building_happens_before_the_connection_opens(monkeypatch):
    """Opus review (round 1) on AUD-0021: _prediction_kwargs_from_analysis's
    run_trend fetch can make up to 3 sequential HTTP calls (its own
    docstring: up to ~60s worst case). tracker._conn has no connect()
    timeout override (5s sqlite3 default), so building those kwargs WHILE
    the batched write's connection/write-lock is held risked starving any
    concurrent writer on tracker.db. Must build every opp's kwargs in a
    pass that runs entirely before the connection opens."""
    import contextlib

    import tracker

    _place_everything_setup(monkeypatch)
    monkeypatch.setattr("order_executor._hourly_gates_active", lambda: False)

    conn_open = {"value": False}
    real_conn = tracker._conn

    @contextlib.contextmanager
    def _tracking_conn():
        conn_open["value"] = True
        try:
            with real_conn() as con:
                yield con
        finally:
            conn_open["value"] = False

    monkeypatch.setattr(tracker, "_conn", _tracking_conn)

    saw_conn_open_during_kwargs = []
    real_kwargs_fn = order_executor._prediction_kwargs_from_analysis

    def _spy_kwargs(a):
        saw_conn_open_during_kwargs.append(conn_open["value"])
        return real_kwargs_fn(a)

    monkeypatch.setattr("order_executor._prediction_kwargs_from_analysis", _spy_kwargs)

    opp = _make_flat_opp("KXTEMPNYCH-26JUL2021-T75.99")

    order_executor._auto_place_trades([opp], client=None)

    assert saw_conn_open_during_kwargs == [False], (
        "kwargs building (including the run_trend HTTP fetch) ran while "
        "the tracker connection/write-lock was held"
    )
    rows = _fetch("KXTEMPNYCH-26JUL2021-T75.99")
    assert len(rows) == 1 and rows[0]["is_shadow"] == 1, (
        "positive control: the opp must still actually get logged, proving "
        "the spy didn't just short-circuit real behavior"
    )
