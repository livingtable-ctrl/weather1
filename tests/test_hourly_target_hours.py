"""Tests for refresh_hourly_target_hours()/get_hourly_target_hour_role() —
once-per-city-per-day cache refresh feeding the KXTEMPxxxH hourly model's
target-hour gate (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2
handoff item 6). Mirrors test_series_drift.py's state-file test pattern.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _today():
    return datetime.now(UTC).date()


def _mock_client(markets_by_series):
    client = MagicMock()
    client.get_markets.side_effect = lambda series_ticker, **kw: markets_by_series.get(
        series_ticker, []
    )
    return client


def _finalized_market(close_time, floor_strike, result):
    return {
        "status": "finalized",
        "close_time": close_time,
        "floor_strike": floor_strike,
        "result": result,
    }


def _ladder_at_local_hour(city_tz, local_hour, proxy_temp, day="2026-06-01"):
    """One finalized ladder whose close_time, converted to `city_tz`, lands
    on `local_hour` — computed via zoneinfo (not a hardcoded offset), so this
    is correct for every city's real timezone, not just America/New_York."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    local_dt = _dt.strptime(f"{day} {local_hour:02d}:00", "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo(city_tz)
    )
    close_time = local_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        _finalized_market(close_time, proxy_temp - 0.5, "yes"),
        _finalized_market(close_time, proxy_temp + 0.5, "no"),
    ]


def test_first_run_creates_cache_for_all_cities(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    markets_by_series = {}
    for series, city in wm._KXTEMP_HOURLY_CITY.items():
        tz = wm._CITY_TZ[city]
        markets = _ladder_at_local_hour(tz, 14, 80.0) + _ladder_at_local_hour(
            tz, 6, 60.0
        )
        markets_by_series[series] = markets

    client = _mock_client(markets_by_series)
    wm.refresh_hourly_target_hours(client)

    assert cache_path.exists()
    state = json.loads(cache_path.read_text())
    for city in wm._KXTEMP_HOURLY_CITY.values():
        assert state[city]["date"] == _today().isoformat()
        assert state[city]["max_hour"] == 14
        assert state[city]["min_hour"] == 6


def test_gated_to_run_once_per_city_per_day(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    today = _today().isoformat()
    existing = {
        city: {"date": today, "max_hour": 14, "min_hour": 6}
        for city in wm._KXTEMP_HOURLY_CITY.values()
    }
    cache_path.write_text(json.dumps(existing))

    client = _mock_client({})
    wm.refresh_hourly_target_hours(client)

    client.get_markets.assert_not_called()


def test_stale_city_refreshed_others_untouched(tmp_path, monkeypatch):
    """One city already refreshed today, the rest weren't — only the stale
    ones should trigger a fetch."""
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    today = _today().isoformat()
    yesterday = (_today() - timedelta(days=1)).isoformat()
    fresh_city = next(iter(wm._KXTEMP_HOURLY_CITY.values()))
    existing = {
        city: {
            "date": today if city == fresh_city else yesterday,
            "max_hour": 99,
            "min_hour": 98,
        }
        for city in wm._KXTEMP_HOURLY_CITY.values()
    }
    cache_path.write_text(json.dumps(existing))

    markets_by_series = {
        series: (
            _ladder_at_local_hour(wm._CITY_TZ[city], 15, 80.0)
            + _ladder_at_local_hour(wm._CITY_TZ[city], 7, 60.0)
        )
        for series, city in wm._KXTEMP_HOURLY_CITY.items()
    }
    client = _mock_client(markets_by_series)
    wm.refresh_hourly_target_hours(client)

    state = json.loads(cache_path.read_text())
    # Fresh city untouched (still the sentinel 99/98, not recomputed).
    assert state[fresh_city]["max_hour"] == 99
    # Every other city recomputed to the new fetch's result.
    for city in wm._KXTEMP_HOURLY_CITY.values():
        if city == fresh_city:
            continue
        assert state[city]["date"] == today
        assert state[city]["max_hour"] == 15
        assert state[city]["min_hour"] == 7
    fetched_series = {
        c.args[0] if c.args else c.kwargs.get("series_ticker")
        for c in client.get_markets.call_args_list
    }
    fresh_series = next(s for s, c in wm._KXTEMP_HOURLY_CITY.items() if c == fresh_city)
    assert fresh_series not in fetched_series


def test_no_usable_data_not_cached_as_done_for_today(tmp_path, monkeypatch):
    """Confirmed live 2026-07-20: a transient fetch/parse hiccup can return
    markets with no usable finalized-ladder data (determine_hourly_target_
    hours -> {"max_hour": None, "min_hour": None}) even for a genuinely
    active city. Caching that result would lock in the failure until
    tomorrow via the once-per-day gate -- must skip caching so the next
    cron cycle retries instead."""
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    # Markets with no finalized ladders at all -> determine_hourly_target_hours
    # returns {"max_hour": None, "min_hour": None} (compute_hourly_temperature_
    # proxy finds nothing usable), simulating the real transient failure mode.
    client = _mock_client({series: [] for series in wm._KXTEMP_HOURLY_CITY})
    wm.refresh_hourly_target_hours(client)

    assert not cache_path.exists() or json.loads(cache_path.read_text()) == {}, (
        "a None/None result must not be written to the cache"
    )

    # Confirm it retries on the next call rather than treating today as done.
    markets_by_series = {
        series: (
            _ladder_at_local_hour(wm._CITY_TZ[city], 14, 80.0)
            + _ladder_at_local_hour(wm._CITY_TZ[city], 6, 60.0)
        )
        for series, city in wm._KXTEMP_HOURLY_CITY.items()
    }
    client2 = _mock_client(markets_by_series)
    wm.refresh_hourly_target_hours(client2)
    state = json.loads(cache_path.read_text())
    for city in wm._KXTEMP_HOURLY_CITY.values():
        assert state[city]["max_hour"] == 14, "must have retried and succeeded"


def test_never_raises_when_fetch_throws(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    client = MagicMock()
    client.get_markets.side_effect = RuntimeError("Kalshi API down")

    wm.refresh_hourly_target_hours(client)  # must not raise


def test_one_city_fetch_failure_does_not_block_others(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    failing_series = next(iter(wm._KXTEMP_HOURLY_CITY))

    def _side_effect(series_ticker, **kw):
        if series_ticker == failing_series:
            raise RuntimeError("this one city's fetch failed")
        city = wm._KXTEMP_HOURLY_CITY[series_ticker]
        tz = wm._CITY_TZ[city]
        return _ladder_at_local_hour(tz, 14, 80.0) + _ladder_at_local_hour(tz, 6, 60.0)

    client = MagicMock()
    client.get_markets.side_effect = _side_effect
    wm.refresh_hourly_target_hours(client)

    state = json.loads(cache_path.read_text())
    failing_city = wm._KXTEMP_HOURLY_CITY[failing_series]
    assert failing_city not in state
    other_city = next(
        c for s, c in wm._KXTEMP_HOURLY_CITY.items() if s != failing_series
    )
    assert state[other_city]["max_hour"] == 14


# ── get_hourly_target_hour_role() ────────────────────────────────────────────


def test_role_returns_max_for_cached_max_hour(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)
    cache_path.write_text(
        json.dumps({"NYC": {"date": "x", "max_hour": 14, "min_hour": 6}})
    )

    assert wm.get_hourly_target_hour_role("NYC", 14) == "max"


def test_role_returns_min_for_cached_min_hour(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)
    cache_path.write_text(
        json.dumps({"NYC": {"date": "x", "max_hour": 14, "min_hour": 6}})
    )

    assert wm.get_hourly_target_hour_role("NYC", 6) == "min"


def test_role_returns_none_for_non_target_hour(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)
    cache_path.write_text(
        json.dumps({"NYC": {"date": "x", "max_hour": 14, "min_hour": 6}})
    )

    assert wm.get_hourly_target_hour_role("NYC", 9) is None


def test_role_returns_none_when_hour_is_none():
    """Ticker hour-parse failure must gate out safely, not crash."""
    import weather_markets as wm

    assert wm.get_hourly_target_hour_role("NYC", None) is None


def test_role_returns_none_when_cache_missing(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    assert wm.get_hourly_target_hour_role("NYC", 14) is None


def test_role_returns_none_when_city_not_cached(tmp_path, monkeypatch):
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)
    cache_path.write_text(
        json.dumps({"NYC": {"date": "x", "max_hour": 14, "min_hour": 6}})
    )

    assert wm.get_hourly_target_hour_role("Austin", 17) is None


def test_role_degenerate_max_equals_min_prefers_max(tmp_path, monkeypatch):
    """If max_hour and min_hour ever coincide (degenerate data), behavior
    must be deterministic — max wins, per the plan's documented precedence."""
    import weather_markets as wm

    cache_path = tmp_path / "hourly_target_hours.json"
    monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)
    cache_path.write_text(
        json.dumps({"NYC": {"date": "x", "max_hour": 12, "min_hour": 12}})
    )

    assert wm.get_hourly_target_hour_role("NYC", 12) == "max"
