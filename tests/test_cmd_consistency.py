"""Tests for main.cmd_consistency's accumulated shadow-observation report
section -- backlog.txt "RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION
DECISION YET". The live violations table already had coverage via
test_consistency.py's find_violations() tests; this covers the NEW section
printed below it (get_shadow_observation_report()'s accumulated history),
which is genuinely new display logic with no prior test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


def _client():
    return MagicMock()


class TestCmdConsistencyShadowReport:
    def test_no_report_and_no_live_violations_prints_clean_state_only(self, capsys):
        with (
            patch.object(main, "get_weather_markets", return_value=[]),
            patch("main.find_violations", return_value=[]),
            patch("main.get_shadow_observation_report", return_value=None),
        ):
            main.cmd_consistency(_client())

        out = capsys.readouterr().out
        assert "No violations right now" in out
        assert "Rain Shadow-Arb Observation History" not in out

    def test_report_with_zero_cycles_observed_is_not_printed(self, capsys):
        """A freshly-created-but-empty state dict (cycles_observed == 0)
        must not print a misleading '0 cycles, 0%' history section."""
        with (
            patch.object(main, "get_weather_markets", return_value=[]),
            patch("main.find_violations", return_value=[]),
            patch(
                "main.get_shadow_observation_report",
                return_value={
                    "cycles_observed": 0,
                    "cycles_with_violation": 0,
                    "violation_rate": 0.0,
                    "distinct_pairs": 0,
                    "top_pairs": [],
                    "last_updated": None,
                },
            ),
        ):
            main.cmd_consistency(_client())

        out = capsys.readouterr().out
        assert "Rain Shadow-Arb Observation History" not in out

    def test_accumulated_report_prints_summary_and_top_pairs(self, capsys):
        report = {
            "cycles_observed": 40,
            "cycles_with_violation": 10,
            "violation_rate": 0.25,
            "distinct_pairs": 2,
            "top_pairs": [
                {
                    "buy_ticker": "KXRAINDENM-26JUL-1",
                    "sell_ticker": "KXRAINDENM-26JUL-3",
                    "times_seen": 8,
                    "max_edge": 0.09,
                    "last_seen": "2026-08-20T12:00:00+00:00",
                },
                {
                    "buy_ticker": "KXRAINSTPM-26JUL-1",
                    "sell_ticker": "KXRAINSTPM-26JUL-4",
                    "times_seen": 2,
                    "max_edge": 0.03,
                    "last_seen": "2026-08-15T12:00:00+00:00",
                },
            ],
            "last_updated": "2026-08-20T12:00:00+00:00",
        }
        with (
            patch.object(main, "get_weather_markets", return_value=[]),
            patch("main.find_violations", return_value=[]),
            patch("main.get_shadow_observation_report", return_value=report),
        ):
            main.cmd_consistency(_client())

        out = capsys.readouterr().out
        assert "Rain Shadow-Arb Observation History" in out
        assert "40 cycle(s) observed" in out
        assert "10 with a shadow violation" in out
        assert "25.0%" in out
        assert "2 distinct ladder-pair(s)" in out
        assert "KXRAINDENM-26JUL-1" in out
        assert "KXRAINSTPM-26JUL-1" in out
        assert "graduation decision" in out.lower()

    def test_report_still_prints_alongside_live_violations(self, capsys):
        """The two sections are independent -- a live violation existing
        right now must not suppress the accumulated-history section below
        it, and vice versa."""
        from consistency import Violation

        live = Violation(
            buy_ticker="A",
            sell_ticker="B",
            buy_prob=0.3,
            sell_prob=0.4,
            guaranteed_edge=0.1,
            description="live one",
            is_shadow=False,
        )
        report = {
            "cycles_observed": 5,
            "cycles_with_violation": 1,
            "violation_rate": 0.2,
            "distinct_pairs": 1,
            "top_pairs": [
                {
                    "buy_ticker": "C",
                    "sell_ticker": "D",
                    "times_seen": 1,
                    "max_edge": 0.02,
                    "last_seen": "2026-08-20T12:00:00+00:00",
                }
            ],
            "last_updated": "2026-08-20T12:00:00+00:00",
        }
        with (
            patch.object(main, "get_weather_markets", return_value=[]),
            patch("main.find_violations", return_value=[live]),
            patch("main.get_shadow_observation_report", return_value=report),
        ):
            main.cmd_consistency(_client())

        out = capsys.readouterr().out
        assert "Found 1 arbitrage opportunity" in out
        assert "Rain Shadow-Arb Observation History" in out
