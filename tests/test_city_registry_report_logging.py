"""Tests for log_city_registry_report() — once-per-day logging wrapper
around city_registry_report() (backlog.txt "PER-CITY KNOWLEDGE SCATTERED").
Written against the same SERIES_DRIFT_PATH/paths.py state-file convention
as check_series_drift() -- see tests/test_series_drift.py.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _today():
    return datetime.now(UTC).date()


def test_first_run_creates_state_file(tmp_path, monkeypatch):
    import weather_markets as wm

    report_path = tmp_path / "city_registry_report.json"
    monkeypatch.setattr(wm, "CITY_REGISTRY_REPORT_PATH", report_path)

    wm.log_city_registry_report()

    assert report_path.exists()
    state = json.loads(report_path.read_text())
    assert "date" in state
    assert "gaps" in state
    # Real, current gaps (LasVegas/NewOrleans historical_sigma, 10 cities
    # missing climate_indices, Seattle correlation_group) must show up --
    # this isn't asserting zero gaps, it's asserting the report ran for real.
    assert state["gaps"], (
        "Expected real known gaps to be reported (see tests/"
        "test_city_registry_manifest.py's _KNOWN_GAPS) -- got none, which "
        "would mean the report silently didn't run against real registries"
    )

    assert "Seattle" in state["gaps"]
    assert "correlation_group" in state["gaps"]["Seattle"]


def test_gated_to_run_once_per_day(tmp_path, monkeypatch):
    """Second call the same day must be a no-op -- proven by checking the
    state file's mtime/content don't change, since city_registry_report()
    has no external call to assert-not-called on (unlike check_series_
    drift's client.get_series_list)."""
    import weather_markets as wm

    report_path = tmp_path / "city_registry_report.json"
    monkeypatch.setattr(wm, "CITY_REGISTRY_REPORT_PATH", report_path)

    sentinel = {"date": _today().isoformat(), "gaps": {"Sentinel": ["proof"]}}
    report_path.write_text(json.dumps(sentinel))

    wm.log_city_registry_report()

    # If the gate didn't hold, the real report would have overwritten this
    # with the actual (different) gap set.
    assert json.loads(report_path.read_text()) == sentinel


def test_runs_again_on_a_new_day(tmp_path, monkeypatch):
    import weather_markets as wm

    report_path = tmp_path / "city_registry_report.json"
    monkeypatch.setattr(wm, "CITY_REGISTRY_REPORT_PATH", report_path)

    stale = {"date": "2020-01-01", "gaps": {"Sentinel": ["proof"]}}
    report_path.write_text(json.dumps(stale))

    wm.log_city_registry_report()

    state = json.loads(report_path.read_text())
    assert state["date"] == _today().isoformat()
    assert state != stale


def test_never_raises_on_a_broken_state_file(tmp_path, monkeypatch):
    """Same isolation contract as check_series_drift -- a corrupted state
    file must never propagate an exception up into the cron cycle."""
    import weather_markets as wm

    report_path = tmp_path / "city_registry_report.json"
    report_path.write_text("not valid json{{{")
    monkeypatch.setattr(wm, "CITY_REGISTRY_REPORT_PATH", report_path)

    wm.log_city_registry_report()  # must not raise
