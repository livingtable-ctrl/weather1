"""Tests for check_retirement_probation() — once-per-day generation of fresh,
post-retirement evidence for retired forecasting methods, and the
auto-unretirement decision it feeds (backlog.txt "AUTO UN-RETIREMENT").

Written against the same RETIREMENT_PROBATION_PATH/paths.py state-file
convention as check_series_drift()/log_city_registry_report() -- see
tests/test_series_drift.py and tests/test_city_registry_report_logging.py.

Why this exists: analyze_trade()'s retired-method gate returns None before
any prediction is logged, so a retired method could never generate fresh
evidence of recovery on its own. check_retirement_probation() samples live
markets, computes what a retired method WOULD predict via
analyze_trade(bypass_retirement_check=True), and logs those as is_probation=1
predictions purely to feed tracker.brier_score_probation_rolling().
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _today():
    return datetime.now(UTC).date()


@pytest.fixture
def tmp_retirement_state(tmp_path, monkeypatch):
    """Isolate the probation state file and the retired-strategies/pins
    files this function reads/writes through tracker, so tests never touch
    the real data/ directory."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(wm, "RETIREMENT_PROBATION_PATH", tmp_path / "probation.json")
    monkeypatch.setattr(tracker, "_RETIRED_PATH", tmp_path / "retired_strategies.json")
    monkeypatch.setattr(tracker, "_PINS_PATH", tmp_path / "strategy_pins.json")
    return tmp_path


def _mock_client(markets):
    client = MagicMock()
    return client


def _market(ticker="KXHIGH-99JAN01-T75"):
    return {"ticker": ticker, "series_ticker": "KXHIGH"}


def test_noop_when_nothing_retired(tmp_retirement_state, monkeypatch):
    """No currently-retired method -> must not even fetch markets."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(tracker, "get_retired_strategies", lambda: {})
    get_markets_spy = MagicMock(return_value=[_market()])
    monkeypatch.setattr(wm, "get_weather_markets", get_markets_spy)

    wm.check_retirement_probation(_mock_client([]))

    get_markets_spy.assert_not_called()
    assert not wm.RETIREMENT_PROBATION_PATH.exists()


def test_gated_to_run_once_per_day(tmp_retirement_state, monkeypatch):
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    wm.RETIREMENT_PROBATION_PATH.write_text(
        json.dumps({"date": _today().isoformat(), "logged": 0})
    )
    get_markets_spy = MagicMock(return_value=[_market()])
    monkeypatch.setattr(wm, "get_weather_markets", get_markets_spy)

    wm.check_retirement_probation(_mock_client([]))

    get_markets_spy.assert_not_called()


def test_runs_again_on_a_new_day(tmp_retirement_state, monkeypatch):
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    stale = {"date": "2020-01-01", "logged": 0}
    wm.RETIREMENT_PROBATION_PATH.write_text(json.dumps(stale))
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: None)

    wm.check_retirement_probation(_mock_client([]))

    state = json.loads(wm.RETIREMENT_PROBATION_PATH.read_text())
    assert state["date"] == _today().isoformat()
    assert state != stale


def test_never_raises_on_broken_state_file(tmp_retirement_state, monkeypatch):
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    wm.RETIREMENT_PROBATION_PATH.write_text("not valid json{{{")
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [])

    wm.check_retirement_probation(_mock_client([]))  # must not raise


def test_logs_probation_prediction_for_retired_method(
    tmp_retirement_state, monkeypatch
):
    """A sampled market whose bypass-resolved method is currently retired
    must be logged as an is_probation=1 row via analyze_trade's bypass."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    monkeypatch.setattr(
        wm, "get_weather_markets", lambda client: [_market("KXHIGH-99JAN01-T75")]
    )
    monkeypatch.setattr(wm, "is_stale", lambda m: False)

    captured_kwargs = {}

    def _fake_analyze(enriched, *, bypass_retirement_check=False):
        assert bypass_retirement_check is True
        return {
            "forecast_prob": 0.6,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
            "n_members": 12,
            "condition": {"type": "above", "threshold": 75.0},
        }

    def _fake_enrich(m, fetch_forecast=True):
        return {"_city": "NYC", "_date": _today() + timedelta(days=1), **m}

    monkeypatch.setattr(wm, "analyze_trade", _fake_analyze)
    monkeypatch.setattr(wm, "enrich_with_forecast", _fake_enrich)

    def _spy_log_prediction(ticker, city, market_date, analysis, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["ticker"] = ticker
        return True

    monkeypatch.setattr(tracker, "log_prediction", _spy_log_prediction)
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: None)

    wm.check_retirement_probation(_mock_client([]))

    assert captured_kwargs.get("ticker") == "KXHIGH-99JAN01-T75"
    assert captured_kwargs.get("is_probation") is True
    assert captured_kwargs.get("is_shadow") is True

    state = json.loads(wm.RETIREMENT_PROBATION_PATH.read_text())
    assert state["logged"] == 1


def test_skips_market_whose_method_is_not_retired(tmp_retirement_state, monkeypatch):
    """If the bypass-resolved method for a sampled market isn't in the
    retired set, it must not be logged as a probation prediction."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [_market()])
    monkeypatch.setattr(wm, "is_stale", lambda m: False)

    def _fake_analyze(enriched, *, bypass_retirement_check=False):
        return {"method": "normal_dist", "forecast_prob": 0.5}

    monkeypatch.setattr(wm, "analyze_trade", _fake_analyze)
    monkeypatch.setattr(
        wm, "enrich_with_forecast", lambda m, fetch_forecast=True: {"_city": "NYC", **m}
    )

    log_spy = MagicMock(return_value=True)
    monkeypatch.setattr(tracker, "log_prediction", log_spy)
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: None)

    wm.check_retirement_probation(_mock_client([]))

    log_spy.assert_not_called()
    state = json.loads(wm.RETIREMENT_PROBATION_PATH.read_text())
    assert state["logged"] == 0


def test_auto_unretires_when_probation_brier_clears_threshold(
    tmp_retirement_state, monkeypatch
):
    """Once brier_score_probation_rolling() reports a recovered score, the
    method must actually be un-retired via tracker.unretire_strategy()."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: 0.15)

    unretire_spy = MagicMock(return_value=True)
    monkeypatch.setattr(tracker, "unretire_strategy", unretire_spy)

    wm.check_retirement_probation(_mock_client([]))

    unretire_spy.assert_called_once_with("ensemble")


def test_does_not_unretire_when_probation_brier_still_bad(
    tmp_retirement_state, monkeypatch
):
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: 0.35)

    unretire_spy = MagicMock(return_value=True)
    monkeypatch.setattr(tracker, "unretire_strategy", unretire_spy)

    wm.check_retirement_probation(_mock_client([]))

    unretire_spy.assert_not_called()


def test_does_not_unretire_when_insufficient_probation_samples(
    tmp_retirement_state, monkeypatch
):
    """None means "not enough fresh evidence yet" -- must not unretire."""
    import tracker
    import weather_markets as wm

    monkeypatch.setattr(
        tracker, "get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
    )
    monkeypatch.setattr(wm, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(tracker, "brier_score_probation_rolling", lambda m, **kw: None)

    unretire_spy = MagicMock(return_value=True)
    monkeypatch.setattr(tracker, "unretire_strategy", unretire_spy)

    wm.check_retirement_probation(_mock_client([]))

    unretire_spy.assert_not_called()
