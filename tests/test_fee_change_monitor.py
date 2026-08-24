"""Tests for batch-49 item 1's fee-change monitor: cron._check_fee_change
(daily fills-based $0-maker-fee assert) and cron._check_fee_schedule_page
(weekly best-effort kalshi.com/fee-schedule page watch).

No existing test to mirror exactly (new cron tasks) -- follows
test_series_drift.py's convention (monkeypatch the module-level state-file
path constant, mock the client) plus test_batch33_reliability.py's
convention for isolating alerts._HALT_TRANSITION_PATH.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import alerts
import cron


def _today():
    return datetime.now(UTC).date()


def _isolate_halt_transition(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halt.json")


def _mock_client(fills):
    client = MagicMock()
    client.get_fills.return_value = fills
    return client


def _maker_fill(ticker="KXHIGHNY-26AUG24-T80", fee_cost="0.0000", fill_id="f1"):
    return {
        "fill_id": fill_id,
        "ticker": ticker,
        "is_taker": False,
        "fee_cost": fee_cost,
    }


class TestCheckFeeChange:
    def test_first_run_creates_state_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([_maker_fill()])

        cron._check_fee_change(client)

        state = json.loads((tmp_path / "fee_check.json").read_text())
        assert state["date"] == str(_today())

    def test_gated_to_run_once_per_day(self, tmp_path, monkeypatch):
        fee_path = tmp_path / "fee_check.json"
        fee_path.write_text(json.dumps({"date": str(_today())}))
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", fee_path)
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([_maker_fill()])

        cron._check_fee_change(client)

        client.get_fills.assert_not_called()

    def test_zero_fee_maker_fills_do_not_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([_maker_fill(), _maker_fill(fill_id="f2")])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_change(client)

        alert_mock.assert_not_called()

    def test_empty_fill_set_does_not_crash(self, tmp_path, monkeypatch):
        """Go/no-go spec's documented fallback: 'if the account has zero
        real fills, assert against an empty set and note it; the check
        still ships as a forward guard.' Confirmed live 2026-08-24 (this
        account currently has zero fills)."""
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([])

        cron._check_fee_change(client)  # must not raise

        assert (tmp_path / "fee_check.json").exists()

    def test_nonzero_maker_fee_logs_error_and_alerts(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([_maker_fill(fee_cost="0.5600")])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        with caplog.at_level(logging.ERROR):
            cron._check_fee_change(client)

        assert any("NONZERO maker fee" in r.message for r in caplog.records)
        alert_mock.assert_called_once()
        title, message = alert_mock.call_args[0]
        assert "maker fee" in title.lower()
        assert "KXHIGHNY-26AUG24-T80" in message

    def test_taker_fills_are_never_flagged_regardless_of_fee(
        self, tmp_path, monkeypatch
    ):
        """Taker fills are expected to have a real, nonzero fee -- only
        maker (is_taker=False) fills are asserted $0."""
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        taker_fill = {
            "fill_id": "f1",
            "ticker": "KXHIGHNY-26AUG24-T80",
            "is_taker": True,
            "fee_cost": "1.2300",
        }
        client = _mock_client([taker_fill])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_change(client)

        alert_mock.assert_not_called()

    def test_unparseable_fee_cost_is_skipped_not_flagged(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = _mock_client([_maker_fill(fee_cost="not-a-number")])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        with caplog.at_level(logging.WARNING):
            cron._check_fee_change(client)

        assert any("unparseable fee value" in r.message for r in caplog.records)
        alert_mock.assert_not_called()

    def test_missing_fee_field_entirely_warns_not_silently_zero(
        self, tmp_path, monkeypatch, caplog
    ):
        """Opus review follow-up: a maker fill missing BOTH fee_cost and
        fee_cost_fp must warn, not silently read as a confirmed $0 -- the
        account had zero real fills at verification time, so `fee_cost`
        was confirmed only against docs.kalshi.com, never a live response."""
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        fill_no_fee_field = {
            "fill_id": "f1",
            "ticker": "KXHIGHNY-26AUG24-T80",
            "is_taker": False,
        }
        client = _mock_client([fill_no_fee_field])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        with caplog.at_level(logging.WARNING):
            cron._check_fee_change(client)

        assert any(
            "no fee_cost/fee_cost_fp field at all" in r.message for r in caplog.records
        )
        alert_mock.assert_not_called()  # missing != confirmed nonzero

    def test_accepts_fee_cost_fp_spelling(self, tmp_path, monkeypatch):
        """Opus review follow-up: this repo has already seen Kalshi migrate
        fields to a `*_fp` suffix (fill_count_fp, orderbook_fp,
        queue_position_fp) -- the fee-cost field must be read under either
        spelling."""
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        fill = {
            "fill_id": "f1",
            "ticker": "KXHIGHNY-26AUG24-T80",
            "is_taker": False,
            "fee_cost_fp": "0.5600",
        }
        client = _mock_client([fill])
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_change(client)

        alert_mock.assert_called_once()

    def test_alert_fires_only_once_on_repeat_engagement(self, tmp_path, monkeypatch):
        """The false->true edge (alerts.check_halt_transition) must fire
        once per NEW engagement, not every day the condition stays true --
        same reasoning as the anomaly/daily-loss halt alerts."""
        fee_path = tmp_path / "fee_check.json"
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", fee_path)
        _isolate_halt_transition(tmp_path, monkeypatch)
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        client = _mock_client([_maker_fill(fee_cost="0.5600")])
        cron._check_fee_change(client)
        assert alert_mock.call_count == 1

        # Simulate the next day's run still detecting the same condition.
        yesterday = (_today() - timedelta(days=1)).isoformat()
        fee_path.write_text(json.dumps({"date": yesterday}))
        cron._check_fee_change(client)

        assert alert_mock.call_count == 1, (
            "check_halt_transition should suppress a repeat alert for an "
            "unchanged, still-active condition"
        )

    def test_alert_delivery_failure_rolls_back_edge_for_retry(
        self, tmp_path, monkeypatch
    ):
        """batch-33 M-1 pattern: if send_system_alert returns False (total
        delivery failure), the edge must roll back so the next day's
        observation is treated as fresh and retries."""
        fee_path = tmp_path / "fee_check.json"
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", fee_path)
        _isolate_halt_transition(tmp_path, monkeypatch)
        alert_mock = MagicMock(return_value=False)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        client = _mock_client([_maker_fill(fee_cost="0.5600")])
        cron._check_fee_change(client)
        assert alert_mock.call_count == 1

        yesterday = (_today() - timedelta(days=1)).isoformat()
        fee_path.write_text(json.dumps({"date": yesterday}))
        cron._check_fee_change(client)

        assert alert_mock.call_count == 2, (
            "a failed delivery must not permanently consume the edge"
        )

    def test_client_exception_is_caught_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_CHECK_PATH", tmp_path / "fee_check.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        client = MagicMock()
        client.get_fills.side_effect = ConnectionError("boom")

        cron._check_fee_change(client)  # must not raise


class TestCheckFeeSchedulePage:
    def _no_network(self, monkeypatch, response=None, exc=None):
        mock_get = MagicMock()
        if exc is not None:
            mock_get.side_effect = exc
        else:
            mock_get.return_value = response
        monkeypatch.setattr("requests.get", mock_get)
        return mock_get

    def test_first_run_creates_state_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", tmp_path / "sched.json")
        resp = MagicMock(status_code=429)
        self._no_network(monkeypatch, response=resp)

        cron._check_fee_schedule_page()

        state = json.loads((tmp_path / "sched.json").read_text())
        assert state["date"] == str(_today())

    def test_gated_to_run_once_per_week_not_once_per_day(self, tmp_path, monkeypatch):
        sched_path = tmp_path / "sched.json"
        yesterday = (_today() - timedelta(days=1)).isoformat()
        sched_path.write_text(json.dumps({"date": yesterday}))
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", sched_path)
        mock_get = self._no_network(monkeypatch, response=MagicMock(status_code=429))

        cron._check_fee_schedule_page()

        mock_get.assert_not_called()

    def test_runs_again_after_a_week(self, tmp_path, monkeypatch):
        sched_path = tmp_path / "sched.json"
        eight_days_ago = (_today() - timedelta(days=8)).isoformat()
        sched_path.write_text(json.dumps({"date": eight_days_ago}))
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", sched_path)
        mock_get = self._no_network(monkeypatch, response=MagicMock(status_code=429))

        cron._check_fee_schedule_page()

        mock_get.assert_called_once()

    def test_429_is_logged_and_skipped_quietly_no_alert(
        self, tmp_path, monkeypatch, caplog
    ):
        """Confirmed live 2026-08-24: kalshi.com Cloudflare-blocks
        non-interactive fetches with 429. Must log-and-skip, never alert on
        the 429 itself, never retry-loop (single request, no retry logic
        in this function at all)."""
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", tmp_path / "sched.json")
        self._no_network(monkeypatch, response=MagicMock(status_code=429))
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        with caplog.at_level(logging.DEBUG):
            cron._check_fee_schedule_page()

        alert_mock.assert_not_called()
        assert any("429" in r.message for r in caplog.records)

    def test_fetch_exception_is_logged_and_skipped_no_raise(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", tmp_path / "sched.json")
        self._no_network(monkeypatch, exc=ConnectionError("boom"))

        cron._check_fee_schedule_page()  # must not raise

    def test_weather_and_change_markers_trigger_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", tmp_path / "sched.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        resp = MagicMock(
            status_code=200,
            text="Effective next month, weather series fees will change.",
        )
        self._no_network(monkeypatch, response=resp)
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_schedule_page()

        alert_mock.assert_called_once()

    def test_matching_page_does_not_realert_on_unchanged_state(
        self, tmp_path, monkeypatch
    ):
        """Opus review follow-up: a real fee-schedule page will almost
        certainly list weather series alongside an effective date on every
        successful fetch -- without edge-gating this would re-alert every
        week forever once the 429-block ever lifts."""
        sched_path = tmp_path / "sched.json"
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", sched_path)
        _isolate_halt_transition(tmp_path, monkeypatch)
        resp = MagicMock(
            status_code=200,
            text="Effective next month, weather series fees will change.",
        )
        self._no_network(monkeypatch, response=resp)
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_schedule_page()
        assert alert_mock.call_count == 1

        # Simulate next week's run still matching the same markers.
        eight_days_ago = (_today() - timedelta(days=8)).isoformat()
        sched_path.write_text(json.dumps({"date": eight_days_ago}))
        cron._check_fee_schedule_page()

        assert alert_mock.call_count == 1, (
            "check_halt_transition should suppress a repeat alert for an "
            "unchanged, still-matching page"
        )

    def test_page_with_no_relevant_markers_does_not_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cron, "FEE_SCHEDULE_SCRAPE_PATH", tmp_path / "sched.json")
        _isolate_halt_transition(tmp_path, monkeypatch)
        resp = MagicMock(status_code=200, text="Sports and politics fee schedule.")
        self._no_network(monkeypatch, response=resp)
        alert_mock = MagicMock(return_value=True)
        monkeypatch.setattr("notify.send_system_alert", alert_mock)

        cron._check_fee_schedule_page()

        alert_mock.assert_not_called()
