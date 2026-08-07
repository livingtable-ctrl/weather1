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


def test_unknown_rain_ticker_warns_immediately(tmp_path, monkeypatch, caplog):
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1: a genuinely
    novel/unknown KXRAIN* series (e.g. an 11th rain city Kalshi adds later)
    must be flagged, now that the drift-check watches KXRAIN* too."""
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    live_with_extra = [*wm.KNOWN_WEATHER_SERIES, "KXRAINNEWCITYM"]

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_with_extra)
        wm.check_series_drift(client)

    assert any(
        "KXRAINNEWCITYM" in r.message and "not in KNOWN_WEATHER_SERIES" in r.message
        for r in caplog.records
    )


def test_hurricane_next_event_series_present_does_not_warn(tmp_path, monkeypatch):
    """backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
    (2026-08-07): the 2 new series, once present in KNOWN_WEATHER_SERIES,
    must not spuriously warn as "missing" when the live series list also
    has them -- exact-membership matching (not substring), mirroring the
    hurricane-count series' own extension."""
    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    client = _mock_client(wm.KNOWN_WEATHER_SERIES)
    wm.check_series_drift(client)

    # KXNEXTHURDATE/KXNEXTCAT5HURDATE are in KNOWN_WEATHER_SERIES and in the
    # live list -- must not appear in the missing_days state at all.
    state = json.loads(drift_path.read_text())
    missing = state.get("missing_days", {})
    assert "KXNEXTHURDATE" not in missing
    assert "KXNEXTCAT5HURDATE" not in missing


def test_unrecognized_hurricane_series_deliberately_not_flagged(
    tmp_path, monkeypatch, caplog
):
    """Exact-membership matching (not substring) is deliberate, mirroring
    the hurricane-count series' own scoping: a genuinely novel hurricane-
    family series (e.g. a hypothetical Pacific sibling to KXNEXTHURDATE)
    must NOT be flagged by this drift check at all -- it's meant to be
    narrower than is_hurricane_ticker()'s broad marker set, so this can
    never start watching (and implicitly invite someone to "fix" a warning
    for) a hurricane series with no matching parser branch. Not startswith
    KXHIGH/KXLOW/KXRAIN, no "SNOW" substring, and not an exact member of
    either hurricane frozenset -- never enters live_weather at all."""
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    live_with_extra = [*wm.KNOWN_WEATHER_SERIES, "KXNEXTHURDATEPAC"]
    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_with_extra)
        wm.check_series_drift(client)

    assert not any("KXNEXTHURDATEPAC" in r.message for r in caplog.records)


def test_known_untracked_rain_series_suppressed(tmp_path, monkeypatch, caplog):
    """The real subtlety found on plan review: client.get_series_list()
    returns ALL real KXRAIN* series, including a handful this bot
    deliberately doesn't track (dormant daily/one-off variants -- 6 as of
    2026-07-26, was 7 before KXRAINSTPM/St. Petersburg moved to
    KNOWN_WEATHER_SERIES that day). Every one of KNOWN_UNTRACKED_RAIN_SERIES
    must be suppressed, not just the genuinely-unknown case above -- a test
    that only checked the unknown case would pass even if this suppression
    were broken and the drift-check spammed a warning for all of them every
    single day.
    """
    import logging

    import weather_markets as wm

    drift_path = tmp_path / "series_drift_check.json"
    monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

    live_with_untracked = [*wm.KNOWN_WEATHER_SERIES, *wm.KNOWN_UNTRACKED_RAIN_SERIES]

    with caplog.at_level(logging.WARNING):
        client = _mock_client(live_with_untracked)
        wm.check_series_drift(client)

    assert not any("not in KNOWN_WEATHER_SERIES" in r.message for r in caplog.records)
