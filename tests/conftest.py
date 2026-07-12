"""Shared pytest fixtures for the Kalshi weather markets test suite."""

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import main here, at collection time, so its module-level load_dotenv() call
# (main.py:41) fires exactly once, before any fixture or test runs. Module code
# only executes on first import — if we didn't force it here, whichever test
# happens to `import main` first (most tests do this lazily, inside the test
# body) would trigger that load_dotenv() call mid-test, AFTER that test's own
# env-cleanup fixtures already ran, silently re-polluting os.environ for just
# that one test (e.g. TRADING_PAUSED reappearing after being explicitly cleared).
import main as _main  # noqa: F401


@pytest.fixture(autouse=True)
def isolate_retired_strategies(tmp_path, monkeypatch):
    """Redirect tracker._RETIRED_PATH to an empty temp file for every test.

    Prevents the real retired_strategies.json on disk (which may have
    'ensemble' retired) from blocking analyze_trade in unrelated tests.
    Tests that exercise the retirement gate write their own data to the
    redirected path via auto_retire_strategies(), so they still work correctly.
    Tests that need a specific retired state use patch() context managers.
    """
    monkeypatch.setattr("tracker._RETIRED_PATH", tmp_path / "retired_strategies.json")


@pytest.fixture(autouse=True)
def isolate_circuit_breaker_state(tmp_path, monkeypatch):
    """Redirect circuit_breaker._CB_STATE_PATH to a per-test temp file.

    CircuitBreaker.__init__ now calls _load_state() which reads from
    _CB_STATE_PATH. Without isolation, state from one test (or from the
    real data/ directory) leaks into subsequent tests, causing spurious
    open-circuit failures.
    """
    import circuit_breaker

    monkeypatch.setattr(circuit_breaker, "_CB_STATE_PATH", tmp_path / ".cb_state.json")


@pytest.fixture(autouse=True)
def isolate_flash_crash_cb_state(tmp_path, monkeypatch):
    """Redirect circuit_breaker's flash-crash history/cooldown paths to
    per-test temp files, and reset the module-level flash_crash_cb
    singleton's in-memory state.

    flash_crash_cb is a module-level singleton constructed once at import
    time (before this fixture ever runs), so its in-memory _history/
    _cooldowns dicts must be reset directly, not just the path constants --
    redirecting the path alone wouldn't undo whatever it already loaded from
    the real data/ directory at import time. Any test exercising the real
    _auto_place_trades/_validate_trade_opportunity code path calls
    flash_crash_cb.check() on the singleton (not a locally-constructed
    FlashCrashCB()), so without this, one test's price history/cooldowns for
    a shared ticker (e.g. a fixture ticker reused across test files) leaks
    into another test and pollutes the real on-disk .flash_crash_history.json.
    """
    import circuit_breaker

    monkeypatch.setattr(
        circuit_breaker,
        "_FLASH_CRASH_HISTORY_PATH",
        tmp_path / ".flash_crash_history.json",
    )
    monkeypatch.setattr(
        circuit_breaker,
        "_FLASH_CRASH_COOLDOWN_PATH",
        tmp_path / ".flash_crash_cooldowns.json",
    )
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_history", {})
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_cooldowns", {})


@pytest.fixture(autouse=True)
def clear_paper_min_edge_cache():
    """Clear config's mtime-gated PAPER_MIN_EDGE cache before every test.

    _paper_min_edge_default() keys its cache on (walk_forward_params.json mtime,
    param_sweep_results.json mtime), not a permanent @functools.cache — but tests
    that patch config._DATA_DIR to a tmp_path can coincidentally produce the same
    mtime pair (or None, None) an earlier test already cached, which would return
    that earlier test's value instead of freshly computing for the new tmp_path.
    """
    import config

    config._paper_min_edge_cache.clear()


@pytest.fixture(autouse=True)
def clear_metar_cache():
    """Clear the in-process METAR cache before every test.

    metar._METAR_CACHE is a module-level dict with a 5-minute TTL.  If any
    earlier test (or a real network call during collection) populates it for
    a station, all subsequent fetch_metar() calls return the cached value
    without touching the mocked _session, causing every TestFetchMetar test
    to receive real live data instead of the fixture response.
    """
    import metar

    metar._METAR_CACHE.clear()


@pytest.fixture(autouse=True)
def neutral_temperature_scaling(monkeypatch):
    """Patch ml_bias._TEMP_CACHE to neutral T=1.0 before every test.

    data/temperature_scale.json is rewritten by cron retrains and is not git-tracked.
    Tests that call analyze_trade see different probability compressions depending on
    what cron last wrote (e.g. T_above=0.5 amplifies probs toward extremes, causing
    model_mkt_gap to fire non-deterministically). Patching the in-memory cache avoids
    loading the disk file for most tests.

    Tests in test_ml_bias.py that exercise temperature scaling directly reset
    _TEMP_CACHE = None in their test body to force a reload from their own patched
    _TEMP_PATH — those direct assignments bypass monkeypatch and take precedence.
    """
    import ml_bias

    neutral = {
        "above": 1.0,
        "below": 1.0,
        "between": 1.0,
        "global": 1.0,
        "sameday": 1.0,
    }
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE", neutral)


@pytest.fixture(autouse=True)
def isolate_condition_weights(monkeypatch):
    """Snapshot and restore weather_markets._CONDITION_WEIGHTS around every test.

    cmd_calibrate() mutates the dict in place (.clear() + .update()) using the
    module-level singleton. Without this fixture, calibration tests leave behind
    overfitted weights (e.g. ens=0.996) that push analyze_trade blend probs past
    the model_mkt_gap gate (0.25), causing subsequent tests to receive None.
    """
    import weather_markets

    monkeypatch.setattr(
        weather_markets,
        "_CONDITION_WEIGHTS",
        copy.deepcopy(weather_markets._CONDITION_WEIGHTS),
    )


@pytest.fixture(autouse=True)
def isolate_tracker_db(tmp_path, monkeypatch):
    """Redirect tracker.DB_PATH to a per-test temp DB and initialize the schema.

    Prevents 'no such table: outcomes' (and related) errors when any code path
    queries the tracker DB during tests that don't explicitly set one up.
    The _db_initialized flag is also reset so init_db() actually runs against
    the redirected path rather than short-circuiting on the module-level init.
    """
    import tracker

    db = tmp_path / "tracker.db"
    monkeypatch.setattr(tracker, "DB_PATH", db)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()


@pytest.fixture(autouse=True)
def reset_open_meteo_circuit_breaker():
    """Reset all weather_markets circuit breakers before every test.

    There are six CBs (_forecast_cb, _ensemble_cb, _ecmwf_om_cb, _nbm_om_cb,
    _weatherapi_cb, _pirate_cb), all module-level singletons. Any test that
    trips one leaves it open for subsequent tests, causing false failures
    (get_weather_forecast returns None).
    """
    import weather_markets

    for cb in (
        weather_markets._forecast_cb,
        weather_markets._ensemble_cb,
        weather_markets._ecmwf_om_cb,
        weather_markets._nbm_om_cb,
        weather_markets._weatherapi_cb,
        weather_markets._pirate_cb,
    ):
        cb.record_success()  # clears _failure_count and _opened_at
    yield


@pytest.fixture(autouse=True)
def isolate_dynamic_sigma(tmp_path, monkeypatch):
    """Redirect climatology's forecast-sigma cache to a per-test temp file and
    short-circuit weather_markets._load_dynamic_sigma() to return {} for every
    test by default.

    get_historical_sigma() (weather_markets.py) lazily loads+memoizes
    climatology.load_all_sigmas() into a module-level _dynamic_sigma dict on
    first call, and load_all_sigmas() itself computes from the real 30yr
    climate archive (data/climate_*.json, which exist on disk for all 20
    cities) and writes data/forecast_sigma.json on first use. Without this
    fixture: (a) tests would write to the real repo data/ directory as a side
    effect, (b) get_historical_sigma() would return real climate-derived
    values instead of the static _HISTORICAL_SIGMA table values most existing
    tests assert exactly, and (c) whichever test runs first would permanently
    memoize its result (real climate data) for the rest of the process.

    Defaults to the dynamic path being unavailable so get_historical_sigma()
    falls through to the static table for every test that doesn't explicitly
    opt in (same pattern as neutral_temperature_scaling above). Tests that
    want to exercise the dynamic path monkeypatch
    weather_markets._load_dynamic_sigma themselves.
    """
    import climatology
    import weather_markets

    monkeypatch.setattr(
        climatology, "_SIGMA_CACHE_PATH", tmp_path / "forecast_sigma.json"
    )
    monkeypatch.setattr(climatology, "_sigma_mem_cache", {})
    monkeypatch.setattr(weather_markets, "_dynamic_sigma", {})
    monkeypatch.setattr(weather_markets, "_load_dynamic_sigma", lambda: {})


@pytest.fixture(autouse=True)
def isolate_execution_log(tmp_path, monkeypatch):
    """Redirect execution_log.DB_PATH to a per-test temp file.

    execution_log.db is a module-level singleton. Without isolation,
    was_ordered_recently() sees filled rows from prior tests in the same
    process, causing subsequent tests (same ticker) to be incorrectly skipped.
    """
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "execution_log.db")
    monkeypatch.setattr(execution_log, "_initialized", False)


@pytest.fixture(autouse=True)
def _set_dashboard_unprotected(monkeypatch):
    """Set DASHBOARD_UNPROTECTED=true so web_app imports/builds don't require DASHBOARD_PASSWORD."""
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)


@pytest.fixture(autouse=True)
def _clear_trading_paused(monkeypatch):
    """Strip TRADING_PAUSED from the real .env so a developer's local pause
    (e.g. while traveling somewhere Kalshi restricts) doesn't silently fail
    every trade-placement test."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_market():
    """Minimal market dict that passes is_liquid and parse_market_price."""
    return {
        "ticker": "KXHIGHNYCX-25Apr09-T60",
        "series_ticker": "KXHIGHNYCX",
        "title": "Will NYC reach 60°F high on Apr 9?",
        "yes_bid": 55,
        "yes_ask": 60,
        "no_bid": 40,
        "no_ask": 45,
        "volume": 5000,
        "open_interest": 200,
        "close_time": "2025-04-09T23:59:00Z",
        "status": "open",
    }


@pytest.fixture
def sample_forecast():
    """Load sample forecast from fixture JSON file."""
    return json.loads((FIXTURES / "sample_forecast.json").read_text())


@pytest.fixture
def target_date():
    return date.today() + timedelta(days=3)


@pytest.fixture
def sample_markets():
    """Load sample markets from fixture JSON file."""
    return json.loads((FIXTURES / "sample_markets.json").read_text())


@pytest.fixture
def mock_kalshi_client(sample_markets):
    """Mock Kalshi API client with sample market data."""
    client = MagicMock()
    client.get_markets.return_value = sample_markets
    client.get_market.side_effect = lambda ticker: next(
        (m for m in sample_markets if m["ticker"] == ticker), {}
    )
    return client


@pytest.fixture
def mock_forecast(sample_forecast):
    """Patch get_weather_forecast to return fixture data."""
    with patch("weather_markets.get_weather_forecast") as mock:
        mock.side_effect = lambda city, date: sample_forecast.get(city)
        yield mock


@pytest.fixture()
def mock_market():
    """Standard mock Kalshi market dict — must stay in sync with production field names."""
    return {
        "ticker": "KXTEMP-25-NYC-B70-T",
        "volume_fp": 500,
        "volume": 500,
        "open_interest_fp": 1000,
        "open_interest": 1000,
        "yes_bid": "0.60",
        "yes_ask": "0.65",
        "close_time": "2026-04-20T20:00:00Z",
        "_forecast": None,
        "_date": None,
        "_city": None,
        "_hour": None,
        "data_fetched_at": None,
    }


@pytest.fixture(autouse=True)
def isolate_paper_data(tmp_path, monkeypatch):
    """Redirect paper.DATA_PATH to a per-test temp file.

    Prevents open trades, balance, and peak_balance from the real
    data/paper_trades.json leaking into unrelated tests.  Without this,
    kelly_bet_dollars() and drawdown_scaling_factor() inside analyze_trade
    see production state (many open trades, reset peak) and may return None
    when isolated tests expect a valid signal.

    Tests that need a specific paper state (mock_balance_1000, cron_env) apply
    their own monkeypatches on top of this one; the last setattr wins for the
    duration of that test and everything is restored together at teardown.
    """
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")


@pytest.fixture
def mock_balance_1000(tmp_path, monkeypatch):
    """Patch paper to use a temp data file and start with $1000 balance."""
    monkeypatch.setattr("paper.DATA_PATH", tmp_path / "paper_trades.json")
    import importlib

    import paper

    importlib.reload(paper)
    yield paper
