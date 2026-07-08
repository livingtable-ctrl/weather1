"""Tests for check_series_drift() — once-per-day detection of Kalshi ticker
drift against KNOWN_WEATHER_SERIES. No existing test to mirror for this
pattern (_check_prod_reminder itself has zero test coverage), written from
scratch against the SERIES_DRIFT_PATH/paths.py state-file convention.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _today():
    """Matches check_series_drift's own datetime.now(UTC).date() — using
    local date.today() here could flake near UTC midnight."""
    return datetime.now(UTC).date()


def _mock_client(live_tickers):
    client = MagicMock()
    client.get_series_list.return_value = [{"ticker": t} for t in live_tickers]
    return client


def test_first_run_creates_state_file(tmp_path, monkeypatch):
    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    client = _mock_client(wm.KNOWN_WEATHER_SERIES)
    wm.check_series_drift(client)

    assert drift_path.exists()
    state = json.loads(drift_path.read_text())
    assert "date" in state
    assert state["missing_days"] == {}


def test_gated_to_run_once_per_day(tmp_path, monkeypatch):
    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    drift_path.write_text(
        json.dumps({"date": _today().isoformat(), "missing_days": {}})
    )

    client = _mock_client(wm.KNOWN_WEATHER_SERIES)
    wm.check_series_drift(client)

    client.get_series_list.assert_not_called()


def test_missing_ticker_counter_increments_and_warns_at_three(
    tmp_path, monkeypatch, caplog
):
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    missing_ticker = wm.KNOWN_WEATHER_SERIES[0]
    live_minus_one = [t for t in wm.KNOWN_WEATHER_SERIES if t != missing_ticker]

    # Simulate 2 prior consecutive missing days by pre-seeding state, then
    # backdating the stored date so today's call isn't skipped by the gate.
    yesterday = (_today() - timedelta(days=1)).isoformat()
    drift_path.write_text(
        json.dumps({"date": yesterday, "missing_days": {missing_ticker: 2}})
    )

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_minus_one)
        wm.check_series_drift(client)

    assert any(
        "missing from Kalshi's live series list for 3 consecutive days" in r.message
        for r in caplog.records
    )
    state = json.loads(drift_path.read_text())
    assert state["missing_days"][missing_ticker] == 3


def test_missing_ticker_does_not_warn_before_three_days(tmp_path, monkeypatch, caplog):
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    missing_ticker = wm.KNOWN_WEATHER_SERIES[0]
    live_minus_one = [t for t in wm.KNOWN_WEATHER_SERIES if t != missing_ticker]

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_minus_one)
        wm.check_series_drift(client)  # day 1 missing — no warning expected

    assert not any("consecutive days" in r.message for r in caplog.records)
    state = json.loads(drift_path.read_text())
    assert state["missing_days"][missing_ticker] == 1


def test_unknown_live_ticker_warns_immediately(tmp_path, monkeypatch, caplog):
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    live_with_extra = [*wm.KNOWN_WEATHER_SERIES, "KXHIGHTNEWCITY"]

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_with_extra)
        wm.check_series_drift(client)

    assert any(
        "KXHIGHTNEWCITY" in r.message and "not in KNOWN_WEATHER_SERIES" in r.message
        for r in caplog.records
    )


def test_known_dead_series_suppressed(tmp_path, monkeypatch, caplog):
    """Known-dead placeholder series (KNOWN_DEAD_WEATHER_SERIES) must not
    trigger the 'not in KNOWN_WEATHER_SERIES' warning, even though they're
    genuinely absent from KNOWN_WEATHER_SERIES — Kalshi's /series endpoint
    lists them forever with zero open markets, and re-warning about the same
    dead entries every day is exactly the noise this allowlist exists to cut.
    """
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    dead_ticker = next(iter(wm.KNOWN_DEAD_WEATHER_SERIES))
    live_with_dead = [*wm.KNOWN_WEATHER_SERIES, dead_ticker]

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_with_dead)
        wm.check_series_drift(client)

    assert not any("not in KNOWN_WEATHER_SERIES" in r.message for r in caplog.records)


def test_never_raises_when_get_series_list_throws(tmp_path, monkeypatch):
    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    client = MagicMock()
    client.get_series_list.side_effect = RuntimeError("Kalshi API down")

    # Must not raise.
    wm.check_series_drift(client)


def test_recovered_ticker_resets_counter(tmp_path, monkeypatch):
    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    ticker = wm.KNOWN_WEATHER_SERIES[0]
    yesterday = (_today() - timedelta(days=1)).isoformat()
    drift_path.write_text(json.dumps({"date": yesterday, "missing_days": {ticker: 2}}))

    client = _mock_client(wm.KNOWN_WEATHER_SERIES)  # ticker is present again
    wm.check_series_drift(client)

    state = json.loads(drift_path.read_text())
    assert ticker not in state["missing_days"]
